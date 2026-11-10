"""Merge-Revision: Objektspeicher/Wartung/Backup (0113-0115) und main (0113 Element-Konfiguration,
0114-0116 Bussen)

Beide Zweige setzen auf 0112_protocol_todos_snapshot auf und berühren getrennte Tabellen,
die Reihenfolge ist daher egal.

Revision ID: 0117_borg_merge_main
Revises: 0115_backup_system, 0116_attendance_fine_unique
Create Date: 2026-10-16
"""

revision = "0117_borg_merge_main"
down_revision = ("0115_backup_system", "0116_attendance_fine_unique")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
