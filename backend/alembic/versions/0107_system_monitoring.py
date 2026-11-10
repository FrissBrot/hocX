"""Systemstatus und Benachrichtigungen im Platform-Admin (/admin/system, /admin/notifications).

Probleme und Ereignisse tragen neben dem deutschen Text (für ntfy) einen strukturierten
Schlüssel ("<quelle>:<subjekt>", z. B. "job:export_cleanup") und einen Grund ("failing",
"unhealthy", ...), damit die Admin-Oberfläche sie in jeder Sprache anzeigen kann.

- system_alert_state: aktuell offene Probleme (Container unhealthy, Job fehlgeschlagen, ClamAV-
  Signaturen veraltet, ...) - eine Zeile pro Problem-Schlüssel. Dient dem Alarm-Loop zum Erkennen
  von Statuswechseln, damit ntfy nur bei "neu", "schlimmer", "wieder OK" und als Erinnerung
  benachrichtigt, nicht bei jedem Durchlauf.
- system_health_event: Verlauf (Problem aufgetreten/behoben, Container neu gestartet) für die
  Systemstatus-Seite. Aufräumen über log_cleanup_loop.
- platform_notification_settings: genau eine Zeile (id = 1) mit der ntfy-Konfiguration aus der
  Admin-Seite. Das ntfy-Token und das Status-Token für Uptime Kuma liegen verschlüsselt
  (secret_crypto, Schlüssel aus ADMIN_AUTH_SECRET); das Status-Token zusätzlich als SHA-256 zum
  Prüfen, damit der öffentliche Summary-Endpoint nichts entschlüsseln muss.

hocx_app hat via ALTER DEFAULT PRIVILEGES DML auf neuen Tabellen (siehe 0066/0068).

Revision ID: 0107_system_monitoring
Revises: 0106_storage_package_is_bookable
Create Date: 2026-10-11
"""

import sqlalchemy as sa
from alembic import op

revision = "0107_system_monitoring"
down_revision = "0106_storage_package_is_bookable"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "system_alert_state",
        sa.Column("problem_key", sa.Text(), primary_key=True),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("notified_severity", sa.Text(), nullable=True),
        sa.Column("last_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("severity IN ('warning', 'critical')", name="ck_system_alert_state_severity"),
    )
    op.create_table(
        "system_health_event",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("kind IN ('problem', 'resolved', 'container_restart')", name="ck_system_health_event_kind"),
        sa.CheckConstraint("severity IN ('info', 'warning', 'critical')", name="ck_system_health_event_severity"),
    )
    op.create_index("idx_system_health_event_created", "system_health_event", ["created_at"])
    op.create_index("idx_system_health_event_subject", "system_health_event", ["subject", "created_at"])
    op.create_table(
        "platform_notification_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ntfy_enabled", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")),
        sa.Column("ntfy_server_url", sa.Text(), nullable=True),
        sa.Column("ntfy_topic", sa.Text(), nullable=True),
        sa.Column("ntfy_token_encrypted", sa.Text(), nullable=True),
        sa.Column("admin_url", sa.Text(), nullable=True),
        sa.Column("reminder_hours", sa.Integer(), nullable=False, server_default=sa.text("6")),
        sa.Column("status_token_hash", sa.Text(), nullable=True),
        sa.Column("status_token_encrypted", sa.Text(), nullable=True),
        sa.Column("last_send_error", sa.Text(), nullable=True),
        sa.Column("last_send_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint("id = 1", name="ck_platform_notification_settings_singleton"),
        sa.CheckConstraint("reminder_hours BETWEEN 0 AND 168", name="ck_platform_notification_settings_reminder_hours"),
    )


def downgrade() -> None:
    op.drop_table("platform_notification_settings")
    op.drop_table("system_health_event")
    op.drop_table("system_alert_state")
