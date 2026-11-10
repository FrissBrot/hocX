"""Baustein-Bibliothek: element_definition.is_library.

Seit die Sitzungsvorlage ihre Traktanden selbst gestaltet (Vorlagen-Editor), entstehen
Elementdefinitionen auch nur für eine einzige Vorlage. ``is_library`` unterscheidet die
wiederverwendbaren «eigenen Bausteine» (Bibliothek) von solchen Einzelstücken. Alle bestehenden
Definitionen stammen aus dem bisherigen Element-Katalog und bleiben in der Bibliothek (TRUE).

Revision ID: 0155_element_library
Revises: 0154_event_start_time
Create Date: 2026-10-25
"""

from alembic import op

revision = "0155_element_library"
down_revision = "0154_event_start_time"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE public.element_definition ADD COLUMN is_library boolean NOT NULL DEFAULT TRUE")


def downgrade() -> None:
    op.execute("ALTER TABLE public.element_definition DROP COLUMN is_library")
