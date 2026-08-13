"""encrypt PlatformOidcConfig.client_secret at rest

Security audit 2026-08-13, finding M3: the SSO client_secret for the platform-admin login was
stored in plaintext - never exposed over the API, but directly usable on DB compromise / backup
leak. app.core.secret_crypto now encrypts/decrypts it (Fernet, keyed off the existing
ADMIN_AUTH_SECRET - see that module's docstring for why no separate key was introduced). This
migration encrypts whatever value is already sitting in the single config row, so existing
deployments don't need a manual re-save of the SSO settings for the encryption to take effect.

Revision ID: 0052_encrypt_oidc_client_secret
Revises: 0051_cycle_config_tenant_index
Create Date: 2026-08-13
"""

import base64
import hashlib

import sqlalchemy as sa
from alembic import op
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

revision = "0052_encrypt_oidc_client_secret"
down_revision = "0051_cycle_config_tenant_index"
branch_labels = None
depends_on = None


def _fernet() -> Fernet:
    # Mirrors app.core.secret_crypto._fernet() - duplicated rather than imported so this
    # migration keeps working unchanged even if that module's derivation ever changes later.
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.admin_auth_secret.encode()).digest())
    return Fernet(key)


def upgrade() -> None:
    conn = op.get_bind()
    fernet = _fernet()
    rows = conn.execute(sa.text("SELECT id, client_secret FROM platform_oidc_config")).fetchall()
    for row in rows:
        secret = row.client_secret
        if not secret:
            continue
        try:
            fernet.decrypt(secret.encode())
            continue  # already an encrypted token (e.g. migration re-run) - leave it as-is
        except InvalidToken:
            pass
        encrypted = fernet.encrypt(secret.encode()).decode()
        conn.execute(
            sa.text("UPDATE platform_oidc_config SET client_secret = :secret WHERE id = :id"),
            {"secret": encrypted, "id": row.id},
        )


def downgrade() -> None:
    conn = op.get_bind()
    fernet = _fernet()
    rows = conn.execute(sa.text("SELECT id, client_secret FROM platform_oidc_config")).fetchall()
    for row in rows:
        secret = row.client_secret
        if not secret:
            continue
        try:
            plain = fernet.decrypt(secret.encode()).decode()
        except InvalidToken:
            continue  # already plaintext
        conn.execute(
            sa.text("UPDATE platform_oidc_config SET client_secret = :secret WHERE id = :id"),
            {"secret": plain, "id": row.id},
        )
