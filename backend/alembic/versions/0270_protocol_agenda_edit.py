"""Traktanden im Protokoll bearbeiten (Editor 1a): Herkunft und lokale Abweichungen merken.

Im Protokoll-Editor lassen sich Traktanden hinzufügen, umbenennen, ausblenden und umsortieren. Die
Vorlage ändert sich dadurch nie; beim Abschliessen listet der Editor die Abweichungen und übernimmt
auf Wunsch eine Auswahl in die Vorlage. Dafür braucht es pro Protokoll-Traktandum:

- ``origin``: Herkunft (``template`` aus der Vorlage, ``protocol`` im Editor hinzugefügt,
  ``session`` «Sitzungsnotizen», ``import`` aus dem Word-Import). Der Vorlagen-Abgleich löscht nur
  Traktanden aus der Vorlage; die anderen bleiben immer stehen.
- ``template_title_snapshot``: Titel laut Vorlage, sobald das Traktandum im Protokoll umbenannt
  wurde (NULL = nicht umbenannt). Der Abgleich behält den eigenen Titel und führt nur diesen nach.
- ``visibility_customized``: Sichtbarkeit im Protokoll geändert; der Abgleich behält sie.

und pro Protokoll ``agenda_order_customized`` (Reihenfolge im Protokoll geändert; der Abgleich
behält sie und fügt neue Vorlagen-Traktanden hinter ihrem Vorlagen-Vorgänger ein).

Neu wird ``template_element.is_visible`` beim Erstellen/Abgleichen übernommen (bisher ungenutzt,
immer TRUE) - so kann ein im Protokoll ausgeblendetes Traktandum in die Vorlage übernommen werden.

Keine neue Tabelle: protocol_element hängt wie bisher über protocol (RLS 0134) am Mandanten.
Spalten mit konstantem Default sind in PostgreSQL ohne Tabellenumschreibung; die Rückfüllung
betrifft nur Sitzungsnotizen und Word-Import-Traktanden.

Revision ID: 0270_protocol_agenda_edit
Revises: 0254_upload_rejections
Create Date: 2026-11-23
"""

import sqlalchemy as sa
from alembic import op

revision = "0270_protocol_agenda_edit"
down_revision = "0254_upload_rejections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "protocol_element",
        sa.Column("origin", sa.Text(), nullable=False, server_default=sa.text("'template'")),
    )
    op.create_check_constraint(
        "ck_protocol_element_origin",
        "protocol_element",
        "origin IN ('template', 'protocol', 'session', 'import')",
    )
    op.add_column("protocol_element", sa.Column("template_title_snapshot", sa.Text(), nullable=True))
    op.add_column(
        "protocol_element",
        sa.Column("visibility_customized", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")),
    )
    op.add_column(
        "protocol",
        sa.Column("agenda_order_customized", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")),
    )
    # Bestand: Sitzungsnotizen (ohne Vorlagenbezug, fester Name) und Word-Import-Traktanden
    op.execute("""
        UPDATE protocol_element
           SET origin = 'session'
         WHERE template_element_id IS NULL AND section_name_snapshot = 'Sitzungsnotizen'
    """)
    op.execute("""
        UPDATE protocol_element pe
           SET origin = 'import'
         WHERE pe.template_element_id IS NULL
           AND pe.origin = 'template'
           AND EXISTS (
               SELECT 1 FROM protocol_element_block b
                WHERE b.protocol_element_id = pe.id
                  AND b.configuration_snapshot_json ? 'word_import_custom_block'
           )
    """)


def downgrade() -> None:
    op.drop_column("protocol", "agenda_order_customized")
    op.drop_column("protocol_element", "visibility_customized")
    op.drop_column("protocol_element", "template_title_snapshot")
    op.drop_constraint("ck_protocol_element_origin", "protocol_element", type_="check")
    op.drop_column("protocol_element", "origin")
