"""Listen: Quelle der Gruppenstatistik als Markierung statt fester Listenname.

Bisher zählte die Statistik nur Termin-Tags aus der Liste, die genau «Gruppen» heisst
(statistics_common.GROUPS_LIST_NAME). Neu markiert ``list_definition.is_group_source`` die
Liste(n), deren Einträge als Gruppen gelten. Bestehende Listen namens «Gruppen» werden markiert,
damit sich an der Statistik nichts ändert. Neue Spalte einer bestehenden Tabelle (RLS gilt schon).

Revision ID: 0176_list_group_source
Revises: 0175_submission_clean_files
Create Date: 2026-11-12
"""

from alembic import op

revision = "0176_list_group_source"
down_revision = "0175_submission_clean_files"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # IF NOT EXISTS: auf dem Test-Stack wurde die Spalte vor dem Image-Neubau von Hand angelegt.
    op.execute("ALTER TABLE list_definition ADD COLUMN IF NOT EXISTS is_group_source BOOLEAN NOT NULL DEFAULT FALSE")
    op.execute("UPDATE list_definition SET is_group_source = TRUE WHERE name = 'Gruppen'")  # sql-ok: fester Text


def downgrade() -> None:
    op.execute("ALTER TABLE list_definition DROP COLUMN IF EXISTS is_group_source")
