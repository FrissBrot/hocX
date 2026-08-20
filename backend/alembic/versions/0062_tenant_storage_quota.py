"""add storage_quota_bytes to tenant for the per-tenant storage quota feature"""

revision = "0062_tenant_storage_quota"
down_revision = "0061_tenant_last_word_import"

import sqlalchemy as sa
from alembic import op


def upgrade():
    op.add_column(
        "tenant",
        sa.Column("storage_quota_bytes", sa.BigInteger(), nullable=True),
    )


def downgrade():
    op.drop_column("tenant", "storage_quota_bytes")
