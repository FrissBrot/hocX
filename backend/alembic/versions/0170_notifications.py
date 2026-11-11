"""Benachrichtigungen per E-Mail: zentraler Versandweg (app/notifications/).

- `platform_notification_settings` (Singleton von /admin/notifications) bekommt die
  SMTP-Konfiguration. Das Passwort liegt nur verschlüsselt vor (secret_crypto), wie das ntfy-Token.
- `notification`: eine Benachrichtigung je Empfänger (Warteschlange und Versandprotokoll). Fachcode
  legt Zeilen in seiner Transaktion an (notifications.publish); der Versand-Loop im job-worker
  bündelt fällige Zeilen je Empfänger und Gruppe zu einer Mail. `dedupe_key` verhindert dieselbe
  Benachrichtigung zweimal (z. B. dieselbe Erinnerung an zwei Tagen).
- `notification_preference`: Kategorie je Person ein/aus (Standard: ein).
- `app_user.notify_without_login`: Personen ohne Login bekommen nur Mails, wenn ein Admin das
  einschaltet.

Revision ID: 0170_notifications
Revises: 0169_todo_fines
Create Date: 2026-11-11
"""

from alembic import op

revision = "0170_notifications"
down_revision = "0169_todo_fines"
branch_labels = None
depends_on = None

SCOPE = "(SELECT public.hocx_rls_tenant())"
BASE = f"({SCOPE} IS NULL OR tenant_id = {SCOPE})"


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE platform_notification_settings
            ADD COLUMN email_enabled boolean NOT NULL DEFAULT false,
            ADD COLUMN smtp_host text,
            ADD COLUMN smtp_port integer NOT NULL DEFAULT 587,
            ADD COLUMN smtp_security text NOT NULL DEFAULT 'starttls',
            ADD COLUMN smtp_username text,
            ADD COLUMN smtp_password_encrypted text,
            ADD COLUMN email_from_address text,
            ADD COLUMN email_from_name text NOT NULL DEFAULT 'hocX',
            ADD COLUMN email_link_base_url text,
            ADD COLUMN email_last_sent_at timestamptz,
            ADD COLUMN email_last_error text,
            ADD COLUMN email_last_error_at timestamptz,
            ADD CONSTRAINT ck_platform_notification_settings_smtp_security CHECK (smtp_security IN ('starttls', 'ssl', 'none')),
            ADD CONSTRAINT ck_platform_notification_settings_smtp_port CHECK (smtp_port BETWEEN 1 AND 65535)
        """
    )
    op.execute("ALTER TABLE app_user ADD COLUMN notify_without_login boolean NOT NULL DEFAULT false")
    op.execute(
        """
        CREATE TABLE notification (
            id bigserial PRIMARY KEY,
            public_id uuid NOT NULL DEFAULT uuidv7() UNIQUE,
            tenant_id bigint NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            recipient_id bigint NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
            kind text NOT NULL,
            group_key text NOT NULL,
            subject_id bigint,
            payload jsonb NOT NULL DEFAULT '{}'::jsonb,
            dedupe_key text,
            status text NOT NULL DEFAULT 'pending',
            skip_reason text,
            deliver_after timestamptz NOT NULL DEFAULT now(),
            attempts integer NOT NULL DEFAULT 0,
            last_error text,
            sent_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_notification_status CHECK (status IN ('pending', 'sent', 'skipped', 'failed')),
            CONSTRAINT uq_notification_dedupe_key UNIQUE (dedupe_key)
        )
        """
    )
    op.execute("CREATE INDEX idx_notification_tenant ON notification (tenant_id)")
    op.execute("CREATE INDEX idx_notification_recipient ON notification (recipient_id, created_at)")
    op.execute("CREATE INDEX idx_notification_pending ON notification (deliver_after) WHERE status = 'pending'")
    op.execute(
        """
        CREATE TABLE notification_preference (
            tenant_id bigint NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            user_id bigint NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
            category text NOT NULL,
            enabled boolean NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (user_id, category)
        )
        """
    )
    op.execute("CREATE INDEX idx_notification_preference_tenant ON notification_preference (tenant_id)")
    for table in ("notification", "notification_preference"):
        op.execute(f"CREATE POLICY tenant_isolation ON public.{table} FOR ALL USING {BASE} WITH CHECK {BASE}")  # sql-ok: feste Bezeichner und Policy-Ausdrücke
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")  # sql-ok: fester Tabellenname


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS notification_preference")
    op.execute("DROP TABLE IF EXISTS notification")
    op.execute("ALTER TABLE app_user DROP COLUMN IF EXISTS notify_without_login")
    op.execute(
        """
        ALTER TABLE platform_notification_settings
            DROP CONSTRAINT IF EXISTS ck_platform_notification_settings_smtp_port,
            DROP CONSTRAINT IF EXISTS ck_platform_notification_settings_smtp_security,
            DROP COLUMN IF EXISTS email_last_error_at,
            DROP COLUMN IF EXISTS email_last_error,
            DROP COLUMN IF EXISTS email_last_sent_at,
            DROP COLUMN IF EXISTS email_link_base_url,
            DROP COLUMN IF EXISTS email_from_name,
            DROP COLUMN IF EXISTS email_from_address,
            DROP COLUMN IF EXISTS smtp_password_encrypted,
            DROP COLUMN IF EXISTS smtp_username,
            DROP COLUMN IF EXISTS smtp_security,
            DROP COLUMN IF EXISTS smtp_port,
            DROP COLUMN IF EXISTS smtp_host,
            DROP COLUMN IF EXISTS email_enabled
        """
    )
