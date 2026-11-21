"""1.5.1: zentraler Status des E-Mail-Versands (app/notifications/delivery_status.py).

Ergänzt ``platform_notification_settings`` (Plattform-Einstellungen, kein Mandantenbezug, daher
keine RLS) um Fehler in Folge, Fehlerklasse und «gestört seit». Letzter Erfolg und letzter Fehler
liegen schon in ``email_last_sent_at``/``email_last_error[_at]`` (0170).

Nummer 0210: 0209 ist für feat/admin-redesign-1.5.1 reserviert; beim Zusammenführen wird
``down_revision`` ggf. angepasst.
"""
from __future__ import annotations

from alembic import op

revision = "0210_email_delivery_status"
down_revision = "0208_platform_metrics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE platform_notification_settings
            ADD COLUMN email_failure_count integer NOT NULL DEFAULT 0,
            ADD COLUMN email_failure_reason text,
            ADD COLUMN email_failing_since timestamptz,
            ADD CONSTRAINT ck_platform_notification_settings_email_failure_reason CHECK (
                email_failure_reason IS NULL OR email_failure_reason IN (
                    'connection', 'timeout', 'tls', 'auth', 'sender_rejected', 'recipient_rejected', 'message_rejected', 'rejected', 'other'
                )
            )
        """
    )
    # Bestand: ein noch offener letzter Fehler zählt als ein Fehler (Klasse unbekannt)
    op.execute(
        """
        UPDATE platform_notification_settings
           SET email_failure_count = 1, email_failure_reason = 'other', email_failing_since = email_last_error_at
         WHERE email_last_error IS NOT NULL AND email_last_error_at IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE platform_notification_settings
            DROP CONSTRAINT IF EXISTS ck_platform_notification_settings_email_failure_reason,
            DROP COLUMN IF EXISTS email_failing_since,
            DROP COLUMN IF EXISTS email_failure_reason,
            DROP COLUMN IF EXISTS email_failure_count
        """
    )
