"""Fotos, die automatisch (Upload-/Sync-Pipeline) in ein geteiltes Album einsortiert werden,
sind erst nach manueller Freigabe fuer die Partner sichtbar: photo_album_item.share_pending
markiert solche Fotos. Beim Galerie-Upload kann die Freigabe direkt mitgegeben werden
(gallery_upload_job.release_to_shared_albums). Bestehende Eintraege gelten als freigegeben.

Revision ID: 0096_album_item_share_pending
Revises: 0095_tenant_trust
Create Date: 2026-09-27
"""

import sqlalchemy as sa
from alembic import op

revision = "0096_album_item_share_pending"
down_revision = "0095_tenant_trust"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("photo_album_item", sa.Column("share_pending", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")))
    op.create_index(
        "idx_photo_album_item_share_pending",
        "photo_album_item",
        ["album_id"],
        postgresql_where=sa.text("share_pending"),
    )
    op.add_column(
        "gallery_upload_job",
        sa.Column("release_to_shared_albums", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")),
    )


def downgrade() -> None:
    op.drop_column("gallery_upload_job", "release_to_shared_albums")
    op.drop_index("idx_photo_album_item_share_pending", table_name="photo_album_item")
    op.drop_column("photo_album_item", "share_pending")
