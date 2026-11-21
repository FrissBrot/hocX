"""Fotoalben: Herkunft automatischer Einträge, damit eine Datumskorrektur sie nachziehen kann.

photo_album_item.auto_source (text, NULL):
- "capture_date": das Foto steht nur wegen seines Aufnahmedatums in diesem Perioden-Album
  (Upload mit Ziel «Zyklus», photo_album_service.assign_uploaded_files). Ändert eine
  Datumskorrektur die Periode, verschiebt photo_album_service.follow_capture_date_change den
  Eintrag in das neue Perioden-Album (User-Entscheid «Nachziehen», 1.5.1).
- NULL: manuell hinzugefügt oder nicht datumsabhängig (Abgabe, bewusst gewählter Termin) - wird nie
  automatisch verschoben.

Bestand bleibt NULL: Ob ein vorhandener Eintrag automatisch oder von Hand ins Album kam, ist nicht
gespeichert; im Zweifel gilt er als manuell und wird nicht angefasst.

Keine neue Tabelle, RLS unverändert (Policy über photo_album, 0134).

Revision ID: 0218_album_item_auto_source
Revises: 0217_file_keywords_synonyms
Create Date: 2026-11-21
"""

import sqlalchemy as sa
from alembic import op

revision = "0218_album_item_auto_source"
down_revision = "0217_file_keywords_synonyms"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("photo_album_item", sa.Column("auto_source", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_photo_album_item_auto_source",
        "photo_album_item",
        "auto_source IS NULL OR auto_source IN ('capture_date')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_photo_album_item_auto_source", "photo_album_item", type_="check")
    op.drop_column("photo_album_item", "auto_source")
