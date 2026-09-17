"""add album_synced_at to submission_upload_file (bounds photo_album_service.sync_submission_uploads' per-tick scan)"""

revision = "0071_submission_album_synced"
down_revision = "0070_stored_file_dimensions"
branch_labels = None
depends_on = None

import sqlalchemy as sa
from alembic import op


def upgrade():
    op.add_column("submission_upload_file", sa.Column("album_synced_at", sa.DateTime(timezone=True), nullable=True))
    # hocx_app already has table-wide SELECT/INSERT/DELETE/UPDATE on submission_upload_file
    # (baseline_schema.sql), which covers this new column too - no extra GRANT needed (same
    # note as 0066/0070). hocx_abgabebox's SELECT/INSERT never needs to touch this column -
    # only the main backend's periodic sync loop reads/writes it.


def downgrade():
    op.drop_column("submission_upload_file", "album_synced_at")
