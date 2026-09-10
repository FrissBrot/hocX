"""Persistent tenant photo albums."""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision = "0065_photo_albums"
down_revision = "0064_table_snapshot"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("photo_album",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False))
    op.create_index("ix_photo_album_tenant_id", "photo_album", ["tenant_id"])
    op.create_table("photo_album_item",
        sa.Column("album_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("photo_album.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("file_id", postgresql.UUID(as_uuid=True), primary_key=True))


def downgrade():
    op.drop_table("photo_album_item")
    op.drop_table("photo_album")
