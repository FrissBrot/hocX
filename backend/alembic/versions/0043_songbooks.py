"""add songbooks

Revision ID: 0043_songbooks
Revises: 0042_protocol_live_responsible
"""

import sqlalchemy as sa
from alembic import op

revision = "0043_songbooks"
down_revision = "0042_protocol_live_responsible"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "songbook",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("created_by", sa.BigInteger(), sa.ForeignKey("app_user.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("tenant_id", "title", name="uq_songbook_tenant_title"),
    )
    op.create_index("idx_songbook_tenant_updated", "songbook", ["tenant_id", "updated_at"])
    op.create_table(
        "songbook_song",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("songbook_id", sa.BigInteger(), sa.ForeignKey("songbook.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("artist", sa.Text(), nullable=False),
        sa.Column("album", sa.Text()),
        sa.Column("duration_seconds", sa.Integer()),
        sa.Column("lyrics", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("source_name", sa.Text()),
        sa.Column("source_id", sa.Text()),
        sa.Column("sort_index", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("idx_songbook_song_book_sort", "songbook_song", ["songbook_id", "sort_index"])


def downgrade() -> None:
    op.drop_table("songbook_song")
    op.drop_table("songbook")
