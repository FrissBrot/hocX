"""add platform_admin table, remove superadmin role from customer model"""

revision = "0033_platform_admin"
down_revision = "0032_stored_file_scan_status"

import sqlalchemy as sa
from alembic import op


def upgrade():
    op.create_table(
        "platform_admin",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("email", sa.Text, nullable=False),
        sa.Column("password_hash", sa.Text, nullable=False),
        sa.Column("display_name", sa.Text, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="TRUE"),
        sa.Column("session_revoke_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("email", name="uq_platform_admin_email"),
    )

    # superadmin was a global cross-tenant role on the customer AppUser model.
    # That capability now lives exclusively in the separate platform_admin system.
    op.execute(
        "DELETE FROM user_role WHERE role_id = (SELECT id FROM role WHERE code = 'superadmin')"
    )
    op.execute("DELETE FROM role WHERE code = 'superadmin'")


def downgrade():
    # NOT FULLY REVERSIBLE (audit I7, 2026-08-16): this recreates the 'superadmin' role
    # itself, but not the user_role rows upgrade() deleted - whoever was superadmin before
    # this migration does not automatically become superadmin again after a downgrade. Was
    # a deliberate simplification for the admin-panel split (platform_admin is the new
    # source of truth going forward), just never called out as such here before.
    op.execute(
        "INSERT INTO role (code, description) VALUES ('superadmin', 'Global access across all tenants') "
        "ON CONFLICT (code) DO NOTHING"
    )
    op.drop_table("platform_admin")
