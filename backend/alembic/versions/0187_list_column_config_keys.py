"""Live-Konfigurationen auf Spalten-Keys umstellen (Plan «Listen mit dynamischen Spalten», 3.2)

Schreibt jede gespeicherte Referenz auf die festen Listenspalten auf den Key der Spalte
(list_column.key, über legacy_key) um: Bausteine, Vorlagen-Traktanden und -Blöcke, Blöcke offener
Protokolle (inklusive ihrer Listen-Snapshots, v1 -> v2), Dokumentvorlagen und Abgaben. Referenzen
auf Listen, die nicht mehr existieren, werden geleert (Gruppierung/Sortierung/Filter entfallen).
Die Logik steckt in app/services/list_column_migration.py (getestet).

Abgeschlossene Protokolle bleiben eingefroren (v1), der Adapter stuft sie beim Lesen hoch.
Der Änderungszähler der Protokoll-Blöcke (Trigger aus 0149) zählt bei dieser reinen
Schlüsselumstellung nicht hoch.

Word-Import: die Felder einer Word-Zeile heissen jetzt first_*/second_* (erste/zweite Zelle)
statt nach den alten Listenspalten; gespeicherte Analysen und Entwürfe werden umbenannt.

Downgrade: Keys der beiden ursprünglichen Spalten werden wieder zu den alten Namen, Keys später
angelegter Spalten entfallen. Bereits hochgestufte Snapshots offener Protokolle bleiben v2 - der
sichere Rückweg ist das Backup vor dem Update (RUNBOOK).

Revision ID: 0187_list_column_config_keys
Revises: 0186_list_columns
Create Date: 2026-11-18
"""
import json
import logging
import re

import sqlalchemy as sa
from alembic import op

from app.services import list_column_migration as m

revision = "0187_list_column_config_keys"
down_revision = "0186_list_columns"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")

_WORD_FIELD = re.compile(r"^column_(one|two)_(raw|type|names|display|source)$")


def _rename_word_fields(value):
    if isinstance(value, list):
        return [_rename_word_fields(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        match = _WORD_FIELD.match(key) if isinstance(key, str) else None
        new_key = f"{'first' if match.group(1) == 'one' else 'second'}_{match.group(2)}" if match else key
        result[new_key] = _rename_word_fields(item)
    return result


def _update_json(conn, table: str, column: str, rows) -> None:
    for row_id, value in rows:
        conn.execute(
            sa.text(f"UPDATE public.{table} SET {column} = CAST(:value AS jsonb) WHERE id = :id"),  # sql-ok: feste Tabellen-/Spaltennamen
            {"value": json.dumps(value), "id": row_id},
        )


BATCH_SIZE = 500


def _batched(conn, query: str):
    """Zeilen (id, Wert) stapelweise nach id lesen statt ganzer Tabellen auf einmal (Speicher bei
    grossen Instanzen). ``query`` ist eine feste Abfrage aus dieser Migration mit Spalte ``id``."""
    after = -1
    while True:
        rows = conn.execute(
            sa.text(f"SELECT * FROM ({query}) AS q WHERE q.id > :after ORDER BY q.id LIMIT :size"),  # sql-ok: feste Abfragen dieser Migration
            {"after": after, "size": BATCH_SIZE},
        ).all()
        if not rows:
            return
        yield [(row[0], row[1]) for row in rows]
        after = rows[-1][0]


def upgrade() -> None:
    conn = op.get_bind()
    key_map: m.KeyMap = {}
    for definition_id, public_id, legacy_key, key in conn.execute(
        sa.text(
            "SELECT d.id, d.public_id, c.legacy_key, c.key FROM public.list_definition d "
            "JOIN public.list_column c ON c.list_definition_id = d.id WHERE c.legacy_key IS NOT NULL"
        )
    ):
        key_map.setdefault(definition_id, {})[legacy_key] = key
        key_map[str(public_id).lower()] = key_map[definition_id]

    def run(table: str, column: str, query: str, rewrite) -> None:
        report = m.Report()
        for rows in _batched(conn, query):
            _update_json(conn, table, column, m.rewrite_rows(rows, lambda value: rewrite(value, report)))
        logger.info(report.line(f"{table}.{column}"))

    run("element_definition", "configuration_json", "SELECT id, configuration_json FROM public.element_definition",
        lambda value, report: m.rewrite_element_definition(value, key_map, report))
    run("template_element", "configuration_json", "SELECT id, configuration_json FROM public.template_element",
        lambda value, report: m.rewrite_block_config(value, key_map, report))
    run("template_element_block", "configuration_override_json",
        "SELECT id, configuration_override_json FROM public.template_element_block WHERE configuration_override_json IS NOT NULL",
        lambda value, report: m.rewrite_block_config(value, key_map, report))

    op.execute("ALTER TABLE public.protocol_element_block DISABLE TRIGGER trg_protocol_element_block_config_version")
    run(
        "protocol_element_block", "configuration_snapshot_json",
        "SELECT b.id, b.configuration_snapshot_json FROM public.protocol_element_block b "
        "JOIN public.protocol_element e ON e.id = b.protocol_element_id JOIN public.protocol p ON p.id = e.protocol_id "
        "WHERE p.status <> 'abgeschlossen' AND b.configuration_snapshot_json IS NOT NULL",
        lambda value, report: m.rewrite_block_config(value, key_map, report, upgrade_snapshots=True),
    )
    op.execute("ALTER TABLE public.protocol_element_block ENABLE TRIGGER trg_protocol_element_block_config_version")

    run("document_template_revision", "content_json", "SELECT id, content_json FROM public.document_template_revision",
        lambda value, report: m.rewrite_studio_params(value, key_map, report))
    run("document_component", "node_json", "SELECT id, node_json FROM public.document_component",
        lambda value, report: m.rewrite_studio_params(value, key_map, report))

    report = m.Report()
    for assignment_id, list_id, source in conn.execute(
        sa.text(
            "SELECT id, list_definition_id, responsible_participant_source FROM public.submission_assignment "
            "WHERE source_type = 'list' AND responsible_participant_source IS NOT NULL"
        )
    ).all():
        new_source = m.rewrite_responsible_source(source, key_map.get(list_id), report, list_id)
        if new_source != source:
            conn.execute(
                sa.text("UPDATE public.submission_assignment SET responsible_participant_source = :source WHERE id = :id"),
                {"source": new_source, "id": assignment_id},
            )
    logger.info(report.line("submission_assignment.responsible_participant_source"))

    for column in ("analysis_snapshot_json", "review_draft_json"):
        for rows in _batched(conn, f"SELECT id, {column} FROM public.word_import_document"):  # sql-ok: fester Spaltenname
            _update_json(conn, "word_import_document", column, m.rewrite_rows(rows, _rename_word_fields))


def _replace_values(value, reverse: dict[str, str | None]):
    """Ersetzt Textwerte, die genau ein Spalten-Key sind (Keys sind UUIDs: kein Zufallstreffer)."""
    if isinstance(value, list):
        return [_replace_values(item, reverse) for item in value]
    if isinstance(value, dict):
        return {key: _replace_values(item, reverse) for key, item in value.items()}
    if isinstance(value, str) and value in reverse:
        return reverse[value]
    return value


def downgrade() -> None:
    conn = op.get_bind()
    reverse: dict[str, str | None] = {
        key: legacy_key for key, legacy_key in conn.execute(sa.text("SELECT key, legacy_key FROM public.list_column"))
    }
    targets = (
        ("element_definition", "configuration_json", "SELECT id, configuration_json FROM public.element_definition"),
        ("template_element", "configuration_json", "SELECT id, configuration_json FROM public.template_element"),
        ("template_element_block", "configuration_override_json",
         "SELECT id, configuration_override_json FROM public.template_element_block WHERE configuration_override_json IS NOT NULL"),
        ("protocol_element_block", "configuration_snapshot_json",
         "SELECT id, configuration_snapshot_json FROM public.protocol_element_block WHERE configuration_snapshot_json IS NOT NULL"),
        ("document_template_revision", "content_json", "SELECT id, content_json FROM public.document_template_revision"),
        ("document_component", "node_json", "SELECT id, node_json FROM public.document_component"),
    )
    op.execute("ALTER TABLE public.protocol_element_block DISABLE TRIGGER trg_protocol_element_block_config_version")
    for table, column, query in targets:
        for rows in _batched(conn, query):
            _update_json(conn, table, column, m.rewrite_rows(rows, lambda value: _replace_values(value, reverse)))
    op.execute("ALTER TABLE public.protocol_element_block ENABLE TRIGGER trg_protocol_element_block_config_version")
    for assignment_id, source in conn.execute(
        sa.text("SELECT id, responsible_participant_source FROM public.submission_assignment WHERE responsible_participant_source IS NOT NULL")
    ).all():
        if source in reverse:
            conn.execute(
                sa.text("UPDATE public.submission_assignment SET responsible_participant_source = :source WHERE id = :id"),
                {"source": reverse[source], "id": assignment_id},
            )
