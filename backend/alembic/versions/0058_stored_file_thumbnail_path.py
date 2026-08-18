"""add thumbnail_path to stored_file for fast-loading file previews"""

revision = "0058_stored_file_thumbnail_path"
down_revision = "0057_stored_file_perceptual_hash"

import sqlalchemy as sa
from alembic import op


def upgrade():
    op.add_column("stored_file", sa.Column("thumbnail_path", sa.Text, nullable=True))
    # abgabebox already has table-wide INSERT/SELECT on stored_file (0020/0023), same as
    # perceptual_hash in 0057 - no extra GRANT needed. Thumbnails for submission uploads are
    # generated lazily by the main backend on first request (see FileService.ensure_thumbnail),
    # not by abgabebox-backend itself.


def downgrade():
    op.drop_column("stored_file", "thumbnail_path")
