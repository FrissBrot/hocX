"""Fehlerprotokoll ohne E-Mail-Adressen (Datenschutz-Audit PRIV-002)

system_error_log speicherte die E-Mail des auslösenden Kontos als Text. Nach dem Löschen einer
Person blieb sie damit bis zum Ablauf der Frist lesbar. Neu verweisen actor_user_id bzw.
actor_admin_id auf das Konto (ON DELETE SET NULL); die Admin-Ansicht löst die Adresse beim Lesen
auf. Bestehende Einträge werden zugeordnet, soweit die Adresse noch einem Konto gehört, danach
wird actor_email geleert. Die Spalte bleibt für die Abgabebox (schreibt NULL) bestehen.

Revision ID: 0139_error_log_actor_ids
Revises: 0138_tenant_stats_visibility
Create Date: 2026-10-21
"""

import sqlalchemy as sa
from alembic import op

revision = "0139_error_log_actor_ids"
down_revision = "0138_tenant_stats_visibility"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "system_error_log",
        sa.Column("actor_user_id", sa.BigInteger(), sa.ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True),
    )
    op.add_column(
        "system_error_log",
        sa.Column("actor_admin_id", sa.BigInteger(), sa.ForeignKey("platform_admin.id", ondelete="SET NULL"), nullable=True),
    )
    op.execute(
        """
        UPDATE system_error_log e SET actor_user_id = u.id
        FROM app_user u
        WHERE e.actor_email IS NOT NULL AND u.login_enabled AND u.email = lower(e.actor_email)
        """
    )
    op.execute(
        """
        UPDATE system_error_log e SET actor_admin_id = a.id
        FROM platform_admin a
        WHERE e.actor_email IS NOT NULL AND e.actor_user_id IS NULL AND lower(a.email) = lower(e.actor_email)
        """
    )
    op.execute("UPDATE system_error_log SET actor_email = NULL WHERE actor_email IS NOT NULL")
    op.execute("CREATE INDEX idx_system_error_log_actor_user ON system_error_log (actor_user_id) WHERE actor_user_id IS NOT NULL")
    op.execute("CREATE INDEX idx_system_error_log_actor_admin ON system_error_log (actor_admin_id) WHERE actor_admin_id IS NOT NULL")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_system_error_log_actor_admin")
    op.execute("DROP INDEX IF EXISTS idx_system_error_log_actor_user")
    op.drop_column("system_error_log", "actor_admin_id")
    op.drop_column("system_error_log", "actor_user_id")
