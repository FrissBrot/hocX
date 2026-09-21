"""Live Photos in der Galerie: gallery_image.live_video_stored_file_id.

Ein Live Photo ist ein Standbild plus ein kurzer Clip. Der Clip ist ein eigener stored_file (damit
Speicherkontingent, Zugriffspruefung und Content-Endpoint unveraendert greifen), hat aber keine
gallery_image-Zeile und taucht deshalb nicht selbst in der Fotos-Uebersicht auf - das Bild verweist
ueber diese Spalte auf ihn. ON DELETE SET NULL: verschwindet der Clip, bleibt das Bild als
normales Foto bestehen.
"""

revision = "0081_gallery_live_photo"
down_revision = "0080_submission_manual_source"
branch_labels = None
depends_on = None

import sqlalchemy as sa
from alembic import op


def upgrade():
    op.add_column("gallery_image", sa.Column("live_video_stored_file_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_gallery_image_live_video_stored_file",
        "gallery_image",
        "stored_file",
        ["live_video_stored_file_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("idx_gallery_image_live_video", "gallery_image", ["live_video_stored_file_id"])


def downgrade():
    op.drop_index("idx_gallery_image_live_video", table_name="gallery_image")
    op.drop_constraint("fk_gallery_image_live_video_stored_file", "gallery_image", type_="foreignkey")
    op.drop_column("gallery_image", "live_video_stored_file_id")
