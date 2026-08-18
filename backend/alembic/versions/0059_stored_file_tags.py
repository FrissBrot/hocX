"""add tags to stored_file for the "Dateien" overview page's tag filter/editor"""

revision = "0059_stored_file_tags"
down_revision = "0058_stored_file_thumbnail_path"

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


def upgrade():
    op.add_column(
        "stored_file",
        sa.Column("tags", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    op.create_index(
        "idx_stored_file_tags_gin", "stored_file", ["tags"], postgresql_using="gin"
    )
    # abgabebox already has table-wide INSERT/SELECT on stored_file (0020/0023), same as
    # perceptual_hash/thumbnail_path - no extra GRANT needed. Tags are only ever written by
    # the main backend (tenant writers editing the "Dateien" page), never by abgabebox-backend
    # itself.


def downgrade():
    op.drop_index("idx_stored_file_tags_gin", table_name="stored_file")
    op.drop_column("stored_file", "tags")
