"""add width/height to stored_file (Fotos gallery placeholder sizing)"""

revision = "0070_stored_file_dimensions"
down_revision = "0069_photo_gallery_context"
branch_labels = None
depends_on = None

import sqlalchemy as sa
from alembic import op


def upgrade():
    op.add_column("stored_file", sa.Column("width", sa.Integer, nullable=True))
    op.add_column("stored_file", sa.Column("height", sa.Integer, nullable=True))
    # abgabebox already has table-wide INSERT/SELECT on stored_file (0020/0023), which
    # covers these new columns too - no extra GRANT needed (same note as 0057/0066).


def downgrade():
    op.drop_column("stored_file", "height")
    op.drop_column("stored_file", "width")
