"""Abgaben: Elemente nach dem Enddatum offen halten (submission_assignment.keep_open_after_end)

Ohne die Option schliesst die Abgabebox ein Element nach dem Ende des Zeitfensters bzw. dem
Stichtag (wie bisher). Mit der Option bleibt es danach offen, bis es nach den normalen Kriterien
schliesst: auto_close (erste Abgabe, maximale Dateizahl) oder von Hand. Die Pendenz behält das
Enddatum als Fälligkeit und wird danach überfällig (Pendenzen-Bussen laufen wie bei jeder Pendenz).

Die Rolle hocx_abgabebox braucht keine neuen Rechte: submission_assignment ist tabellenweit lesbar.

Revision ID: 0173_submission_keep_open
Revises: 0172_fine_tariff_attendance
Create Date: 2026-11-11
"""

import sqlalchemy as sa
from alembic import op

revision = "0173_submission_keep_open"
down_revision = "0172_fine_tariff_attendance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "submission_assignment",
        sa.Column("keep_open_after_end", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("submission_assignment", "keep_open_after_end")
