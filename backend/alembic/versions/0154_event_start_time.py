"""Uhrzeit für Termine: event.start_time (optional).

Gesetzt vom Block «Nächste Sitzung» (selected_time) und beim Erstellen des Folgeprotokolls
wieder übernommen. Bestehende Termine bleiben ganztägig (NULL).

Revision ID: 0154_event_start_time
Revises: 0153_agenda_item
Create Date: 2026-10-25
"""

from alembic import op

revision = "0154_event_start_time"
down_revision = "0153_agenda_item"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE public.event ADD COLUMN start_time time without time zone")


def downgrade() -> None:
    op.execute("ALTER TABLE public.event DROP COLUMN start_time")
