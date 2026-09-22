"""Persisted EXIF capture date on stored_file, plus an auto-linked flag on gallery_image
so date-based Termin linking can be told apart from a manually picked one."""
from alembic import op
import sqlalchemy as sa

revision = "0083_photo_capture_event_link"
down_revision = "0082_upload_exact_duplicates"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("stored_file", sa.Column("exif_taken_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("idx_stored_file_exif_taken_at", "stored_file", ["exif_taken_at"])
    op.add_column(
        "gallery_image",
        sa.Column("event_auto_linked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade():
    op.drop_column("gallery_image", "event_auto_linked")
    op.drop_index("idx_stored_file_exif_taken_at", table_name="stored_file")
    op.drop_column("stored_file", "exif_taken_at")
