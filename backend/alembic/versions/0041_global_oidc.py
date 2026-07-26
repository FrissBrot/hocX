"""remove tenant-scoped OIDC, add a single global platform OIDC config for admin-panel SSO

hocX moves from "each tenant can configure its own OIDC provider" (insecure and unused - see
security audit 2026-07-26, tenant_oidc_config had 0 configured rows and app_user.oidc_subject
had 0 non-null values in production) to a single, globally configured SSO provider used
exclusively to log into the platform-admin panel. Regular tenant/customer users keep
password-only login.

Revision ID: 0041_global_oidc
Revises: 0040_missing_legacy_columns
Create Date: 2026-07-26
"""

from alembic import op
import sqlalchemy as sa

revision = "0041_global_oidc"
down_revision = "0040_missing_legacy_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("tenant_oidc_config")

    op.drop_constraint("app_user_oidc_issuer_oidc_subject_key", "app_user", type_="unique")
    op.drop_index("idx_app_user_oidc", table_name="app_user")
    op.drop_column("app_user", "oidc_subject")
    op.drop_column("app_user", "oidc_issuer")
    op.drop_column("app_user", "oidc_email")

    op.create_table(
        "platform_oidc_config",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")),
        sa.Column("issuer_url", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("client_id", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("client_secret", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("scopes", sa.Text(), nullable=False, server_default=sa.text("'openid email profile'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
    )

    op.add_column("platform_admin", sa.Column("oidc_subject", sa.Text(), nullable=True))
    op.add_column("platform_admin", sa.Column("oidc_issuer", sa.Text(), nullable=True))
    op.create_unique_constraint("uq_platform_admin_oidc", "platform_admin", ["oidc_issuer", "oidc_subject"])


def downgrade() -> None:
    op.drop_constraint("uq_platform_admin_oidc", "platform_admin", type_="unique")
    op.drop_column("platform_admin", "oidc_issuer")
    op.drop_column("platform_admin", "oidc_subject")

    op.drop_table("platform_oidc_config")

    op.add_column("app_user", sa.Column("oidc_email", sa.Text(), nullable=True))
    op.add_column("app_user", sa.Column("oidc_issuer", sa.Text(), nullable=True))
    op.add_column("app_user", sa.Column("oidc_subject", sa.Text(), nullable=True))
    op.create_index("idx_app_user_oidc", "app_user", ["oidc_issuer", "oidc_subject"])
    op.create_unique_constraint("app_user_oidc_issuer_oidc_subject_key", "app_user", ["oidc_issuer", "oidc_subject"])

    op.create_table(
        "tenant_oidc_config",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")),
        sa.Column("auto_redirect", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")),
        sa.Column("issuer_url", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("client_id", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("client_secret", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("scopes", sa.Text(), nullable=False, server_default=sa.text("'openid email profile'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", name="tenant_oidc_config_tenant_id_key"),
    )
