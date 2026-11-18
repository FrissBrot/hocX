"""Termine: Endzeit, zwei Spezial-Uhrzeiten und Programm.

start_time gab es schon (Sitzungsdatum-Block «Nächster Hock»), jetzt kommt die Endzeit dazu, zwei
frei benennbare Uhrzeitfelder (spezial_time1/2, Alias und Ausblenden wie die übrigen
Spezialfelder in tenant_setting.event_field_config) und ein Textfeld «Programm». Textfelder
eines Termins (Beschreibung, Programm, Spezial-Texte) enthalten Markdown; bestehende Texte sind
gültiges Markdown und bleiben unverändert.

Revision ID: 0184_event_times_program
Revises: 0183_abgabebox_link_scope
Create Date: 2026-11-18
"""

from alembic import op

revision = "0184_event_times_program"
down_revision = "0183_abgabebox_link_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE event
          ADD COLUMN IF NOT EXISTS end_time time,
          ADD COLUMN IF NOT EXISTS spezial_time1 time,
          ADD COLUMN IF NOT EXISTS spezial_time2 time,
          ADD COLUMN IF NOT EXISTS program text
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE event
          DROP COLUMN IF EXISTS program,
          DROP COLUMN IF EXISTS spezial_time2,
          DROP COLUMN IF EXISTS spezial_time1,
          DROP COLUMN IF EXISTS end_time
        """
    )
