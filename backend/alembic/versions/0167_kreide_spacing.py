"""Gestaltungsbeispiel «Kreide»: grössere Abstände (Zeilen, Absätze, Traktanden).

Das Beispiel war sehr eng gesetzt (Zeilenabstand 1.35, Absatzabstand 2.5 mm, Abschnittsabstand
6.5 mm). Neu 1.5 / 3 mm / 10 mm (app/documents/examples.py). Brand-Profile mit dem Grundstil
«kreide» bekommen eine neue Revision mit den neuen Werten - je Wert nur, wenn er noch genau den
bisherigen Wert des Beispiels trägt; bewusst geänderte Werte bleiben. Revisionen sind
unveränderlich (Exporte halten die verwendete fest), bereits erstellte PDFs bleiben gleich.
Kein Downgrade der Daten: die vorherige Revision lässt sich im Corporate Design wiederherstellen
(wie 0159_brand_section_gap).

Revision ID: 0167_kreide_spacing
Revises: 0166_perf_job_run_indexes
Create Date: 2026-11-09
"""

import copy
import hashlib
import json

import sqlalchemy as sa
from alembic import op

revision = "0167_kreide_spacing"
down_revision = "0166_perf_job_run_indexes"
branch_labels = None
depends_on = None

# (Bereich, Feld): (alter Wert, neuer Wert)
_BUMP = {
    ("typography", "line_height"): (1.35, 1.5),
    ("layout", "paragraph_gap"): (2.5, 3),
    ("layout", "section_gap"): (6.5, 10),
}
_NOTE = "Abstände des Designs «Kreide» vergrössert (Update)"


def _hash(payload: dict) -> str:
    # Gleich wie app.documents.hashing.json_hash (Migrationen importieren keinen App-Code)
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT b.id, b.current_revision, r.tokens_json FROM document_brand b "
            "JOIN document_brand_revision r ON r.brand_id = b.id AND r.revision = b.current_revision "
            "WHERE r.tokens_json -> 'appearance' ->> 'base' = 'kreide'"
        )
    ).all()
    for brand_id, current, tokens in rows:
        updated = copy.deepcopy(tokens or {})
        changed = False
        for (area, field), (old, new) in _BUMP.items():
            value = updated.get(area, {}).get(field)
            if isinstance(value, (int, float)) and float(value) == old:
                updated[area][field] = new
                changed = True
        if not changed:
            continue
        next_revision = current + 1
        bind.execute(
            sa.text(
                "INSERT INTO document_brand_revision (brand_id, revision, tokens_json, tokens_hash, note) "
                "VALUES (:brand_id, :revision, CAST(:tokens AS jsonb), :hash, :note)"
            ),
            {"brand_id": brand_id, "revision": next_revision, "tokens": json.dumps(updated, ensure_ascii=False), "hash": _hash(updated), "note": _NOTE},
        )
        bind.execute(
            sa.text("UPDATE document_brand SET current_revision = :revision, lock_version = lock_version + 1 WHERE id = :id"),
            {"revision": next_revision, "id": brand_id},
        )


def downgrade() -> None:
    # Datenänderung: die vorherige Revision bleibt erhalten und lässt sich wiederherstellen
    pass
