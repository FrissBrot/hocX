"""Objektspeicher: Löschen erst nach dem Commit (DOCMGMT-005) - im Release 1.2.0 ein No-op.

feature/document-management und feature/s3-storage-maintenance haben dasselbe Verfahren (Tombstone
+ Job storage_purge) unabhängig voneinander eingeführt, mit eigener Revisions-ID, damit beim
Zusammenführen eine der beiden Migrationen zum No-op werden kann. Im Release übernimmt das
0118_storage_purge_after_commit: dessen storage_register_write() baut auf der Rollenbindung aus
0115_storage_role_scoping auf, die Fassung dieses Zweigs noch auf 0113 - liefe sie danach, fiele
die Rollenprüfung (Abgabebox schreibt nur in ihren Namespace) wieder weg.

Revision ID: 0118_docmgmt_storage_purge
Revises: 0117_docmgmt_merge_main
Create Date: 2026-10-16
"""

revision = "0118_docmgmt_storage_purge"
down_revision = "0117_docmgmt_merge_main"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
