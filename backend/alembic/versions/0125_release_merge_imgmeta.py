"""Merge-Revision Release 1.2.0: Bild-Metadaten und Standortfreigabe aus
feature/image-metadata-dedupe (0113_image_capture_metadata bis 0118_album_share_location) mit dem
bisherigen Release-Stand (bis 0124).

Die neuen Spalten liegen auf stored_file/gallery_image bzw. photo_album_tenant_share und
berühren keine Tabellen der anderen Zweige; die Reihenfolge ist egal.

Revision ID: 0125_release_merge_imgmeta
Revises: 0124_release_merge_documents, 0118_album_share_location
Create Date: 2026-10-16
"""

revision = "0125_release_merge_imgmeta"
down_revision = ("0124_release_merge_documents", "0118_album_share_location")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
