"""add tenant_domain table for per-tenant custom domains

Revision ID: 0037_tenant_domain
Revises: 0036_event_is_cancelled
Create Date: 2026-07-20
"""

import sqlalchemy as sa
from alembic import op

revision = "0037_tenant_domain"
down_revision = "0036_event_is_cancelled"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenant_domain",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("domain", sa.Text(), nullable=False),
        sa.Column("verification_token", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint("purpose IN ('app', 'abgabebox')", name="ck_tenant_domain_purpose"),
        sa.CheckConstraint("status IN ('pending', 'active')", name="ck_tenant_domain_status"),
        sa.UniqueConstraint("tenant_id", "purpose", name="uq_tenant_domain_tenant_purpose"),
        sa.UniqueConstraint("domain", name="uq_tenant_domain_domain"),
    )


def downgrade() -> None:
    op.drop_table("tenant_domain")
