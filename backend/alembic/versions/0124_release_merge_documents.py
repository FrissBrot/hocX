"""Merge-Revision Release 1.2.0: logische Dokumente aus feature/document-management
(0115_documents bis 0118_docmgmt_storage_purge) mit dem bisherigen Release-Stand (bis 0123).

Die Tabellen document/document_version/document_file/document_extraction/document_job sind neu und
unabhängig von den Tabellen der Dokument-Engine (document_export, document_registry, document_*
des Document Studio). Protokollexporte der Engine werden seit dem Release-Merge als Versionen
logischer Dokumente geführt (app/services/protocol_export_document_service.py).

Revision ID: 0124_release_merge_documents
Revises: 0123_backup_hold_tombstones, 0118_docmgmt_storage_purge
Create Date: 2026-10-16
"""

revision = "0124_release_merge_documents"
down_revision = ("0123_backup_hold_tombstones", "0118_docmgmt_storage_purge")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
