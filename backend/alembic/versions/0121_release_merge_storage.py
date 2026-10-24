"""Merge-Revision Release 1.2.0: Dokument-Engine/Document Studio (bis 0120) und Objektspeicher/
Wartung aus feature/s3-storage-maintenance (0113-0118).

Beide Zweige berühren getrennte Tabellen (document_* bzw. storage_*/maintenance_*); die
Reihenfolge ist egal. Die Dateien des Document Studio (document_asset.storage_path, erzeugte
PDFs) laufen seit dem Release-Merge über den Objektspeicher (Namespace «main»), es braucht
dafür keine Datenmigration: bestehende Dateien liegen in Generation 0 (Dateisystem) am selben
Key und werden von einer späteren Storage-Migration wie alle anderen übernommen.

Revision ID: 0121_release_merge_storage
Revises: 0120_registry_title_overridden, 0118_storage_purge_after_commit
Create Date: 2026-10-16
"""

revision = "0121_release_merge_storage"
down_revision = ("0120_registry_title_overridden", "0118_storage_purge_after_commit")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
