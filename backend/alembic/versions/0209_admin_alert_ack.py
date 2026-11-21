"""Plattform-Admin 1.5.1: Sicherheitswarnungen quittieren.

``system_alert_state`` hält je offenem Problem eine Zeile und wird gelöscht, sobald das Problem
verschwindet (system_alert_service.evaluate_and_notify). Die Quittung hängt deshalb an dieser Zeile:
eine quittierte Warnung bleibt quittiert, solange sie offen ist, und taucht wieder als offen auf,
wenn sie nach dem Abklingen erneut auftritt. Plattformweit, ohne Mandanten- und Personenbezug
(nur die ID des Plattform-Admins, ``ON DELETE SET NULL``).

Revision ID: 0209_admin_alert_ack
Revises: 0208_platform_metrics
Create Date: 2026-11-21
"""

from alembic import op

revision = "0209_admin_alert_ack"
down_revision = "0208_platform_metrics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE system_alert_state ADD COLUMN acknowledged_at timestamptz")
    op.execute(
        "ALTER TABLE system_alert_state ADD COLUMN acknowledged_by_admin_id bigint "
        "REFERENCES platform_admin(id) ON DELETE SET NULL"
    )
    op.execute("ALTER TABLE system_alert_state ADD COLUMN acknowledged_note text")
    op.execute(
        "ALTER TABLE system_alert_state ADD CONSTRAINT ck_system_alert_state_ack_note "
        "CHECK (acknowledged_note IS NULL OR length(acknowledged_note) <= 500)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE system_alert_state DROP CONSTRAINT IF EXISTS ck_system_alert_state_ack_note")
    op.execute("ALTER TABLE system_alert_state DROP COLUMN IF EXISTS acknowledged_note")
    op.execute("ALTER TABLE system_alert_state DROP COLUMN IF EXISTS acknowledged_by_admin_id")
    op.execute("ALTER TABLE system_alert_state DROP COLUMN IF EXISTS acknowledged_at")
