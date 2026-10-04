"""Canonical element_type ids for the finance/chart/entry_exit blocks

Das Frontend (Vorlagen-Editor, lib/constants/element-types.ts, i18n-Keys elementTypes.<id>)
arbeitet mit festen ids: 12 finance_balance, 13 finance_transactions, 14 fine_list, 15 chart,
16 entry_exit - so wie sie auf der urspruenglichen Datenbank entstanden sind (12-15 per
manuellem SQL, 16 per 0064).

Die 1.0.0-Baseline (sql/baseline_lookup_data.sql) hat aber entry_exit als id 12 angelegt und
die Finanz-/Chart-Typen ganz weggelassen; ensure_lookup_values() in app/main.py haengte sie
danach mit max(id)+1 als 13-16 an. Auf jeder so aufgesetzten Instanz speicherte der Vorlagen-
Editor daher den falschen Typ: "Kontostand" (12) wurde zu entry_exit, "Ein-/Austritte" (16)
zu chart usw. - im Protokoll erschienen Ein-/Austritte unter Finanzen und "Kein Diagramm
ausgewaehlt" statt der Ein-/Austritte.

Alle Referenzen auf ids 12-16 (template_element_block, protocol_element_block,
element_definition.configuration_json) stammen ausschliesslich aus dem Vorlagen-Editor
(kein Backend-Pfad legt diese Typen per Code-Lookup an) und tragen damit die Frontend-
Bedeutung der id. Deshalb werden hier nur die Codes der element_type-Zeilen auf das
kanonische Layout umbenannt - die Referenzen bleiben unveraendert und zeigen danach auf den
Typ, den der Benutzer im Editor gewaehlt hatte. Fehlende Zeilen werden mit fester id
angelegt. Auf bereits kanonischen Datenbanken ist die Migration ein No-op.

Revision ID: 0098_canonical_element_type_ids
Revises: 0097_app_user_preferred_language
Create Date: 2026-10-04
"""

import sqlalchemy as sa
from alembic import op

revision = "0098_canonical_element_type_ids"
down_revision = "0097_app_user_preferred_language"
branch_labels = None
depends_on = None

CANONICAL = {
    12: ("finance_balance", "Finance account balance"),
    13: ("finance_transactions", "Finance transaction table"),
    14: ("fine_list", "Attendance fine list"),
    15: ("chart", "Statistics chart block"),
    16: ("entry_exit", "Participant entry/exit block"),
}


def upgrade() -> None:
    conn = op.get_bind()
    rows = {row.id: row.code for row in conn.execute(sa.text("SELECT id, code FROM element_type"))}
    canonical_codes = {code for code, _ in CANONICAL.values()}

    stray = {element_type_id: code for element_type_id, code in rows.items() if code in canonical_codes and element_type_id not in CANONICAL}
    if stray:
        raise RuntimeError(f"element_type: unerwartete ids fuer kanonische Codes {stray} - bitte manuell pruefen")
    unknown = {element_type_id: code for element_type_id, code in rows.items() if element_type_id in CANONICAL and code not in canonical_codes}
    if unknown:
        raise RuntimeError(f"element_type: ids 12-16 mit unbekannten Codes {unknown} - bitte manuell pruefen")

    if all(rows.get(element_type_id) == code for element_type_id, (code, _) in CANONICAL.items()):
        return

    # code ist UNIQUE - erst auf temporaere Werte, dann auf die kanonischen Codes umbenennen.
    for element_type_id in CANONICAL:
        if element_type_id in rows:
            conn.execute(sa.text("UPDATE element_type SET code = :tmp WHERE id = :id"), {"tmp": f"__tmp_{element_type_id}", "id": element_type_id})
    for element_type_id, (code, description) in CANONICAL.items():
        if element_type_id in rows:
            conn.execute(
                sa.text("UPDATE element_type SET code = :code, description = :description WHERE id = :id"),
                {"code": code, "description": description, "id": element_type_id},
            )
        else:
            conn.execute(
                sa.text("INSERT INTO element_type (id, code, description) VALUES (:id, :code, :description)"),
                {"id": element_type_id, "code": code, "description": description},
            )
    conn.execute(sa.text(
        "SELECT setval(pg_get_serial_sequence('public.element_type', 'id'), (SELECT MAX(id) FROM element_type), true)"
    ))


def downgrade() -> None:
    # Bewusst kein Rueckweg: die alte Belegung war fehlerhaft.
    pass
