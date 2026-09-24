"""add feature catalog + tenant_feature (per-tenant feature gating, finance as pilot feature)

Two tables, orthogonal to the existing role system: `feature` is a small lookup catalog
(one row per gate-able feature), `tenant_feature` is the per-tenant entitlement join, same
shape as TenantDomain (app/models/entities.py). Seeds the 'finance' feature and backfills a
tenant_feature row for every existing tenant - without the backfill, every existing customer
would be locked out of Finanzen the moment this deploys (require_finance_read/write now also
check tenant_feature via require_feature, see app/core/security.py).

Revision ID: 0084_tenant_feature
Revises: 0083_photo_capture_event_link
Create Date: 2026-09-23
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0084_tenant_feature"
down_revision = "0083_photo_capture_event_link"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "feature",
        sa.Column("code", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
    )
    op.create_table(
        "tenant_feature",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("uuidv7()")),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("feature_code", sa.Text(), sa.ForeignKey("feature.code", ondelete="CASCADE"), nullable=False),
        sa.Column("enabled_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("enabled_by_admin_id", sa.BigInteger(), sa.ForeignKey("platform_admin.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("public_id", name="uq_tenant_feature_public_id"),
        sa.UniqueConstraint("tenant_id", "feature_code", name="uq_tenant_feature_tenant_code"),
    )

    bind = op.get_bind()
    bind.execute(
        sa.text("INSERT INTO feature (code, name, description) VALUES ('finance', 'Finanzen', 'Kassenbuch, Beiträge und Bussen')")
    )
    # Backfill: every existing tenant keeps Finanzen (it was unconditionally usable before this
    # migration, gated only by role) - only tenants created after this deploy start unbooked.
    bind.execute(
        sa.text(
            "INSERT INTO tenant_feature (tenant_id, feature_code) SELECT id, 'finance' FROM tenant"
        )
    )


def downgrade() -> None:
    op.drop_table("tenant_feature")
    op.drop_table("feature")
