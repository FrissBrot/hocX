"""requeue quality analysis for images (sharpness is now tile-based, see photo_quality.py)"""

revision = "0076_requeue_quality_scores"
down_revision = "0075_submission_link"
branch_labels = None
depends_on = None

from alembic import op


def upgrade():
    # Old sharpness_score values were a global Laplacian variance; the new ones are the
    # 90th percentile of per-tile variances, which lives on a different scale. Clearing
    # quality_analyzed_at lets FileService.backfill_missing_quality_scores recompute them.
    op.execute("UPDATE stored_file SET quality_analyzed_at = NULL WHERE mime_type LIKE 'image/%'")


def downgrade():
    # Data-only migration; nothing to undo (the old scores are recomputed from disk anyway).
    pass
