"""gallery_image: marks a stored_file as uploaded directly through the "Dateien"/"Fotos"
gallery upload window - not tied to a protocol block, word-import document, or submission
upload (the three other origins in StoredFileRepository._files_overview_branches).

Revision ID: 0063_gallery_image
Revises: 0062_tenant_storage_quota
Create Date: 2026-08-23
"""

import sqlalchemy as sa
from alembic import op

revision = "0063_gallery_image"
down_revision = "0062_tenant_storage_quota"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gallery_image",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("stored_file_id", sa.BigInteger(), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["stored_file_id"], ["stored_file.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["app_user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_gallery_image_tenant", "gallery_image", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("idx_gallery_image_tenant", table_name="gallery_image")
    op.drop_table("gallery_image")
