"""requeue perceptual hash recomputation (hash now respects EXIF rotation and crops uniform borders)"""

revision = "0077_requeue_perceptual_hashes"
down_revision = "0076_requeue_quality_scores"
branch_labels = None
depends_on = None

from alembic import op


def upgrade():
    # FileService.backfill_missing_quality_scores re-hashes every already-hashed image whose
    # quality_analyzed_at is NULL, so clearing it makes the old (rotation-blind, border-blind)
    # hashes get recomputed from disk.
    op.execute("UPDATE stored_file SET quality_analyzed_at = NULL WHERE mime_type LIKE 'image/%' AND perceptual_hash IS NOT NULL")


def downgrade():
    # Data-only migration; nothing to undo.
    pass
