"""Merge-Revision: Document Studio (0114-0118) und Bussen-Reparaturen aus main (0114-0116)

Beide Zweige setzen auf 0113_element_config_schema auf und berühren getrennte Tabellen
(document_* bzw. attendance_fine), die Reihenfolge ist daher egal. Eigener Name, weil
feat/document-engine-typst eine gleichartige Merge-Revision (0118_merge_main_fines) hat.

Revision ID: 0119_studio_merge_main_fines
Revises: 0118_document_studio, 0116_attendance_fine_unique
Create Date: 2026-10-16
"""

revision = "0119_studio_merge_main_fines"
down_revision = ("0118_document_studio", "0116_attendance_fine_unique")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
