"""Einmal-Links für Konten: «Passwort vergessen» und Einladung per E-Mail (Benachrichtigungen Phase 3).

- `account_token`: ein Einmal-Link je Zeile. Gespeichert wird nur der SHA-256-Hash des Tokens;
  das Token selbst entsteht erst beim Versand der Mail (notifications/account.py) und steht nur
  dort, im URL-Fragment des Links. Ein neuer Link derselben Art widerruft die offenen alten.
- Einladung: das Konto bekommt erst beim Einlösen Passwort und Login (ck_app_user_login_credentials
  bleibt unverändert).

Revision ID: 0171_account_tokens
Revises: 0170_notifications
Create Date: 2026-11-11
"""

from alembic import op

revision = "0171_account_tokens"
down_revision = "0170_notifications"
branch_labels = None
depends_on = None

SCOPE = "(SELECT public.hocx_rls_tenant())"
BASE = f"({SCOPE} IS NULL OR tenant_id = {SCOPE})"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE account_token (
            id bigserial PRIMARY KEY,
            tenant_id bigint NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            user_id bigint NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
            purpose text NOT NULL,
            token_hash text,
            created_by_user_id bigint REFERENCES app_user(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            sent_at timestamptz,
            expires_at timestamptz,
            used_at timestamptz,
            revoked_at timestamptz,
            CONSTRAINT ck_account_token_purpose CHECK (purpose IN ('password_reset', 'invite')),
            CONSTRAINT uq_account_token_hash UNIQUE (token_hash)
        )
        """
    )
    op.execute("CREATE INDEX idx_account_token_tenant ON account_token (tenant_id)")
    op.execute("CREATE INDEX idx_account_token_open ON account_token (user_id, purpose) WHERE used_at IS NULL AND revoked_at IS NULL")
    op.execute(f"CREATE POLICY tenant_isolation ON public.account_token FOR ALL USING {BASE} WITH CHECK {BASE}")  # sql-ok: feste Policy-Ausdrücke
    op.execute("ALTER TABLE public.account_token ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS account_token")
