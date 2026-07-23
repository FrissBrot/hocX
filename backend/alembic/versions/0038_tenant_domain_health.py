"""add health-check fields to tenant_domain

Revision ID: 0038_tenant_domain_health
Revises: 0037_tenant_domain
Create Date: 2026-07-22
"""

import sqlalchemy as sa
from alembic import op

revision = "0038_tenant_domain_health"
down_revision = "0037_tenant_domain"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenant_domain", sa.Column("is_healthy", sa.Boolean(), nullable=False, server_default=sa.text("true")))
    op.add_column("tenant_domain", sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("tenant_domain", "last_checked_at")
    op.drop_column("tenant_domain", "is_healthy")
