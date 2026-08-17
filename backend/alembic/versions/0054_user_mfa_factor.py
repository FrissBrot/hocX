"""add user_mfa_factor table for TOTP and passkeys

Introduces explicit per-user MFA factors for customer accounts: encrypted TOTP secrets and
WebAuthn/passkey credentials. Tenant-admin accounts are required to have at least one factor,
while other users can opt in via their profile. The table is separate from app_user so admins
can inspect/reset individual factors without mutating unrelated profile data.

Revision ID: 0054_user_mfa_factor
Revises: 0053_platform_admin_role
Create Date: 2026-08-17
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0054_user_mfa_factor"
down_revision = "0053_platform_admin_role"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_mfa_factor",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("factor_type", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("secret_encrypted", sa.Text(), nullable=True),
        sa.Column("totp_last_counter", sa.BigInteger(), nullable=True),
        sa.Column("webauthn_credential_id", sa.Text(), nullable=True),
        sa.Column("webauthn_public_key_pem", sa.Text(), nullable=True),
        sa.Column("webauthn_sign_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("webauthn_aaguid", sa.Text(), nullable=True),
        sa.Column("webauthn_rp_id", sa.Text(), nullable=True),
        sa.Column(
            "webauthn_transports_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint("factor_type IN ('totp', 'webauthn')", name="ck_user_mfa_factor_type"),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("webauthn_credential_id", name="uq_user_mfa_factor_webauthn_credential_id"),
    )
    op.create_index("idx_user_mfa_factor_user", "user_mfa_factor", ["user_id", "factor_type"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_user_mfa_factor_user", table_name="user_mfa_factor")
    op.drop_table("user_mfa_factor")
