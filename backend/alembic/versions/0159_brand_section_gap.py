"""Corporate Design: grösserer Abstand vor Abschnitten (Traktanden).

Der Standard von ``layout.section_gap`` steigt von 6 auf 8 mm (Vorlage «Kompakt»: 4 auf 5 mm).
Brand-Profile, deren gültige Revision noch genau den bisherigen Standardwert trägt, bekommen eine
neue Revision mit dem neuen Wert. Revisionen sind unveränderlich (Exporte halten die verwendete
fest), deshalb eine neue Revision statt einer Änderung; bereits erstellte PDFs bleiben gleich.
Ein bewusst anderer Wert bleibt unverändert. Kein Downgrade der Daten: die vorherige Revision
lässt sich im Corporate Design wiederherstellen.

Revision ID: 0159_brand_section_gap
Revises: 0158_feature_entitlements
Create Date: 2026-10-28
"""

import copy
import hashlib
import json

import sqlalchemy as sa
from alembic import op

revision = "0159_brand_section_gap"
down_revision = "0158_feature_entitlements"
branch_labels = None
depends_on = None

# alter Wert → neuer Wert
_BUMP = {6: 8, 4: 5}
_NOTE = "Abstand vor Abschnitten vergrössert (Update)"


def _hash(payload: dict) -> str:
    # Gleich wie app.documents.hashing.json_hash (Migrationen importieren keinen App-Code)
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT b.id, b.current_revision, r.tokens_json FROM document_brand b "
            "JOIN document_brand_revision r ON r.brand_id = b.id AND r.revision = b.current_revision"
        )
    ).all()
    for brand_id, current, tokens in rows:
        gap = (tokens or {}).get("layout", {}).get("section_gap")
        if not isinstance(gap, (int, float)) or float(gap) not in _BUMP:
            continue
        updated = copy.deepcopy(tokens)
        updated["layout"]["section_gap"] = _BUMP[float(gap)]
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
