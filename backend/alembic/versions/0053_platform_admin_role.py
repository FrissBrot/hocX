"""add role column to platform_admin

Security audit 2026-08-12, finding N2 (niedrig): every active platform-admin account had
identical, unrestricted rights over every tenant - no read-only support role existed. This adds
a `role` column ('owner' = full read/write, 'support' = read-only across the whole admin panel)
defaulting existing accounts to 'owner' so behavior is unchanged until an operator explicitly
creates/downgrades a support account. Enforced in app.core.admin_security.require_admin_write.

Revision ID: 0053_platform_admin_role
Revises: 0052_encrypt_oidc_client_secret
Create Date: 2026-08-13
"""

import sqlalchemy as sa
from alembic import op

revision = "0053_platform_admin_role"
down_revision = "0052_encrypt_oidc_client_secret"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("platform_admin", sa.Column("role", sa.Text(), nullable=False, server_default="owner"))
    op.create_check_constraint("ck_platform_admin_role", "platform_admin", "role IN ('owner', 'support')")


def downgrade() -> None:
    op.drop_constraint("ck_platform_admin_role", "platform_admin", type_="check")
    op.drop_column("platform_admin", "role")
