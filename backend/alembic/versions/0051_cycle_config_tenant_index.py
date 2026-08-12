"""cycle_config: add missing tenant_id index

Revision ID: 0051_cycle_config_tenant_index
Revises: 0050_word_import_outcome_log
Create Date: 2026-08-11

Note: 0018_cycle_config created the cycle_config table without a tenant_id
index (unlike every other tenant-scoped table, which has one from creation
or via the 0009 index-audit migration) - found during the 2026-08-11 code
audit. Added here as a follow-up rather than editing 0018 directly, since
that revision is already applied in production.
"""

import sqlalchemy as sa
from alembic import op

revision = "0051_cycle_config_tenant_index"
down_revision = "0050_word_import_outcome_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("idx_cycle_config_tenant", "cycle_config", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("idx_cycle_config_tenant", table_name="cycle_config")
