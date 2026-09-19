"""gallery_image gets the Bezug columns for direct document uploads on the "Dateien" page
(POST /files/document-uploads): the Zyklus / Abgabe (+ Abgabe-Element) the file was linked
to, next to the Termin (event_id) it could already point at. Photo uploads keep linking via
auto-albums and leave these NULL."""

revision = "0074_gallery_image_doc_links"
down_revision = "0073_gallery_upload_job"
branch_labels = None
depends_on = None

import sqlalchemy as sa
from alembic import op


def upgrade():
    op.add_column("gallery_image", sa.Column("cycle_config_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_gallery_image_cycle_config", "gallery_image", "cycle_config", ["cycle_config_id"], ["id"], ondelete="SET NULL"
    )
    op.add_column("gallery_image", sa.Column("submission_assignment_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_gallery_image_submission_assignment",
        "gallery_image",
        "submission_assignment",
        ["submission_assignment_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column("gallery_image", sa.Column("submission_element_ref", sa.Text(), nullable=True))
    op.add_column("gallery_image", sa.Column("submission_element_label", sa.Text(), nullable=True))
    op.create_index("idx_gallery_image_cycle_config", "gallery_image", ["cycle_config_id"])
    op.create_index("idx_gallery_image_submission_assignment", "gallery_image", ["submission_assignment_id"])


def downgrade():
    op.drop_index("idx_gallery_image_submission_assignment", table_name="gallery_image")
    op.drop_index("idx_gallery_image_cycle_config", table_name="gallery_image")
    op.drop_column("gallery_image", "submission_element_label")
    op.drop_column("gallery_image", "submission_element_ref")
    op.drop_constraint("fk_gallery_image_submission_assignment", "gallery_image", type_="foreignkey")
    op.drop_column("gallery_image", "submission_assignment_id")
    op.drop_constraint("fk_gallery_image_cycle_config", "gallery_image", type_="foreignkey")
    op.drop_column("gallery_image", "cycle_config_id")
