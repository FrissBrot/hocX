"""Merge-Revision Release 1.2.0: Backup-System aus feature/borg-backup-restore
(0115_backup_system, 0117_borg_merge_main) mit dem bisherigen Release-Stand (bis 0121).

0113_object_storage/0114_maintenance teilen sich beide Zweige (gleiche Revisionen). 0115 legt
Backup-Tabellen, den Copy-on-Write-Hold und storage_backup_hold() an; der Hold wirkt seit dem
Release-Merge auch im Purge-Job (Tombstones, 0118_storage_purge_after_commit), siehe
objstore_client.purge_deleted.

Revision ID: 0122_release_merge_backup
Revises: 0121_release_merge_storage, 0117_borg_merge_main
Create Date: 2026-10-16
"""

revision = "0122_release_merge_backup"
down_revision = ("0121_release_merge_storage", "0117_borg_merge_main")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
