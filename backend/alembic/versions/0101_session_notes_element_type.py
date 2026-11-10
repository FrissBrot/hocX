"""Blocktyp "Sitzungsnotizen" (element_type 17 session_notes)

Zeigt die freien Sitzungsnotizen (protocol.session_notes) als eigenen Block im Protokoll und im
Export - ohne die Sitzungs-Todos. Der Block ist nur drin, wenn er in einer Vorlage hinzugefuegt
wurde; bestehende Vorlagen/Protokolle bleiben unveraendert.

Feste id 17, weil das Frontend (lib/constants/element-types.ts, i18n-Keys elementTypes.<id>)
Blocktypen per id adressiert (siehe 0098_canonical_element_type_ids).

Revision ID: 0101_session_notes_element_type
Revises: 0100_share_link_metadata_privacy
Create Date: 2026-10-05
"""

import sqlalchemy as sa
from alembic import op

revision = "0101_session_notes_element_type"
down_revision = "0100_share_link_metadata_privacy"
branch_labels = None
depends_on = None

ELEMENT_TYPE_ID = 17
CODE = "session_notes"
DESCRIPTION = "Session notes block"


def upgrade() -> None:
    conn = op.get_bind()
    rows = {row.id: row.code for row in conn.execute(sa.text("SELECT id, code FROM element_type"))}
    if rows.get(ELEMENT_TYPE_ID) == CODE:
        return
    if ELEMENT_TYPE_ID in rows:
        raise RuntimeError(f"element_type: id {ELEMENT_TYPE_ID} ist mit {rows[ELEMENT_TYPE_ID]!r} belegt - bitte manuell pruefen")
    if CODE in rows.values():
        raise RuntimeError(f"element_type: Code {CODE!r} existiert mit anderer id - bitte manuell pruefen")
    conn.execute(
        sa.text("INSERT INTO element_type (id, code, description) VALUES (:id, :code, :description)"),
        {"id": ELEMENT_TYPE_ID, "code": CODE, "description": DESCRIPTION},
    )
    conn.execute(sa.text(
        "SELECT setval(pg_get_serial_sequence('public.element_type', 'id'), (SELECT MAX(id) FROM element_type), true)"
    ))


def downgrade() -> None:
    conn = op.get_bind()
    in_use = conn.scalar(sa.text(
        "SELECT EXISTS (SELECT 1 FROM template_element_block WHERE element_type_id = :id)"
        " OR EXISTS (SELECT 1 FROM protocol_element_block WHERE element_type_id = :id)"
    ), {"id": ELEMENT_TYPE_ID})
    if in_use:
        raise RuntimeError("element_type session_notes wird noch von Bloecken verwendet - Downgrade abgebrochen")
    conn.execute(sa.text("DELETE FROM element_type WHERE id = :id AND code = :code"), {"id": ELEMENT_TYPE_ID, "code": CODE})
