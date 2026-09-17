"""add quality_analyzed_at to stored_file (bounds backfill_missing_quality_scores retries)"""

revision = "0072_quality_analyzed_at"
down_revision = "0071_submission_album_synced"
branch_labels = None
depends_on = None

import sqlalchemy as sa
from alembic import op


def upgrade():
    op.add_column("stored_file", sa.Column("quality_analyzed_at", sa.DateTime(timezone=True), nullable=True))
    # hocx_app already has table-wide grants on stored_file (0057/0066/0070 notes) - no
    # extra GRANT needed for a new column.


def downgrade():
    op.drop_column("stored_file", "quality_analyzed_at")
