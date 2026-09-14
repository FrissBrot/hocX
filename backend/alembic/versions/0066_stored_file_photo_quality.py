"""add sharpness/exposure quality scores to stored_file (photo-culling Phase 1)"""

revision = "0066_stored_file_photo_quality"
down_revision = "0066_upload_pipeline_indexes"
branch_labels = None
depends_on = None

import sqlalchemy as sa
from alembic import op


def upgrade():
    op.add_column("stored_file", sa.Column("sharpness_score", sa.Float, nullable=True))
    op.add_column("stored_file", sa.Column("exposure_score", sa.Float, nullable=True))
    # abgabebox already has table-wide INSERT/SELECT on stored_file (0020/0023), which
    # covers these new columns too - no extra GRANT needed (same note as 0057).


def downgrade():
    op.drop_column("stored_file", "exposure_score")
    op.drop_column("stored_file", "sharpness_score")
