"""Spalten einer Liste lesen (Migration 0186): die einzigen Helfer, über die Code Werte, Bezeichnung
und Verantwortliche eines Listeneintrags bestimmt.

Spalten-Keys (``ListColumn.key`` = public_id als Text) sind undurchsichtige Bezeichner: kein Code
prüft auf einen bestimmten Key oder leitet aus ihm Position oder Bedeutung ab. Bedeutung kommt nur
aus den Rollen der Liste (``label_column_id``, ``responsible_column_id``). Alte Keys aus
eingefrorenen Daten (Snapshots, alte Exporte) übersetzt allein ``list_legacy_adapter``.
"""
from __future__ import annotations

from typing import Any

from app.models import ListColumn, ListDefinition, ListEntry
from app.services.block_config_shape import bigint_digits

VALUE_TYPES = ("text", "participant", "participants", "event")
PARTICIPANT_TYPES = ("participant", "participants")
LABEL_TYPES = ("text", "event")
# Grenze je Liste (Entscheid 9.5 des Plans): breite Tabellen bleiben bedienbar, PDFs lesbar
MAX_COLUMNS = 20


def columns_of(definition: ListDefinition | None) -> list[ListColumn]:
    if definition is None:
        return []
    return sorted(definition.columns, key=lambda column: (column.sort_index, column.id or 0))


def resolve_column(definition: ListDefinition | None, key: Any) -> ListColumn | None:
    """Spalte zu einem Key aus einer Konfiguration. Unbekannte Keys ergeben None (die
    Gruppierung/Sortierung/Filterung entfällt dann). Alte Keys aus eingefrorenen Konfigurationen
    löst der v1-Adapter über ``legacy_key`` auf."""
    if definition is None or key in (None, ""):
        return None
    text_key = str(key)
    for column in definition.columns:
        if column.key == text_key:
            return column
    from app.services.list_legacy_adapter import legacy_column

    return legacy_column(definition, text_key)


def column_by_id(definition: ListDefinition | None, column_id: int | None) -> ListColumn | None:
    if definition is None or column_id is None:
        return None
    return next((column for column in definition.columns if column.id == column_id), None)


def get_value(entry: ListEntry | dict, column: ListColumn | str | None) -> dict[str, Any]:
    """Gespeicherter Wert (interne IDs) eines Eintrags in einer Spalte; {} wenn leer."""
    if column is None:
        return {}
    key = column if isinstance(column, str) else column.key
    values = entry.get("values_json") if isinstance(entry, dict) else entry.values_json
    value = (values or {}).get(key)
    return dict(value) if isinstance(value, dict) else {}


def label_column(definition: ListDefinition | None) -> ListColumn | None:
    """Spalte, die einen Eintrag benennt: die Rolle der Liste, sonst die erste Text- oder
    Termin-Spalte, sonst die erste Spalte."""
    column = column_by_id(definition, definition.label_column_id if definition else None)
    if column is not None:
        return column
    columns = columns_of(definition)
    return next((c for c in columns if c.value_type in LABEL_TYPES), columns[0] if columns else None)


def responsible_column(definition: ListDefinition | None) -> ListColumn | None:
    """Spalte mit den verantwortlichen Personen: die Rolle, sonst die erste Personen-Spalte."""
    column = column_by_id(definition, definition.responsible_column_id if definition else None)
    if column is not None and column.value_type in PARTICIPANT_TYPES:
        return column
    return next((c for c in columns_of(definition) if c.value_type in PARTICIPANT_TYPES), None)


def participant_ids_of(value: dict[str, Any] | None, value_type: str) -> list[int]:
    value = value or {}
    if value_type == "participant" and isinstance(value.get("participant_id"), int):
        return [value["participant_id"]]
    if value_type == "participants" and isinstance(value.get("participant_ids"), list):
        return [item for item in value["participant_ids"] if isinstance(item, int)]
    return []


def responsible_ids_of(entry: ListEntry, definition: ListDefinition | None) -> list[int]:
    column = responsible_column(definition)
    return participant_ids_of(get_value(entry, column), column.value_type) if column else []


def all_participant_ids(entry: ListEntry, definition: ListDefinition | None) -> set[int]:
    """Alle Personen eines Eintrags über alle Spalten (Personen-Bereinigung, Datenexport)."""
    ids: set[int] = set()
    for column in columns_of(definition):
        ids.update(participant_ids_of(get_value(entry, column), column.value_type))
    return ids


def event_id_of(value: dict[str, Any] | None) -> int | None:
    event_id = (value or {}).get("event_id")
    return event_id if isinstance(event_id, int) else None


def text_of(value: dict[str, Any] | None, value_type: str, *, participant_names: dict[int, str] | None = None,
            event_titles: dict[int, str] | None = None) -> str:
    """Anzeigetext eines Werts; Namen und Termintitel aus vorab geladenen Zuordnungen."""
    value = value or {}
    if value_type == "text":
        return str(value.get("text_value") or "").strip()
    if value_type in PARTICIPANT_TYPES:
        names = participant_names or {}
        return ", ".join(names[pid] for pid in participant_ids_of(value, value_type) if pid in names)
    if value_type == "event":
        event_id = event_id_of(value)
        return (event_titles or {}).get(event_id, "") if event_id is not None else ""
    return ""


def label_of(entry: ListEntry, definition: ListDefinition | None, *, participant_names: dict[int, str] | None = None,
             event_titles: dict[int, str] | None = None) -> str:
    """Bezeichnung eines Eintrags (Abgabe-Label, Matrix-Spaltentitel, Gruppenname)."""
    column = label_column(definition)
    if column is None:
        return ""
    return text_of(get_value(entry, column), column.value_type, participant_names=participant_names, event_titles=event_titles)


def clear_column_values(values: dict[str, Any] | None, key: str) -> dict[str, Any]:
    return {k: v for k, v in (values or {}).items() if k != key}


# ── Spalten-Keys in Block-Konfigurationen ───────────────────────────────────────────────────

_LIST_KEY_FIELDS = ("linked_list_group_by", "linked_list_sort_by", "linked_list_filter_column")


def _definition(db, list_id: Any, tenant_id: int | None, cache: dict) -> ListDefinition | None:
    """Liste zu einer ID aus einer Konfiguration: interne ID (gespeichert) oder öffentliche UUID
    (vom Client), immer mandantengebunden."""
    if list_id in (None, "") or isinstance(list_id, bool):
        return None
    cache_key = str(list_id)
    if cache_key in cache:
        return cache[cache_key]
    definition = None
    if isinstance(list_id, int) or (isinstance(list_id, str) and list_id.isdigit()):
        # Ziffern ausserhalb von ASCII/BIGINT können keine id sein (int() bzw. die Abfrage scheiterte)
        internal_id = list_id if isinstance(list_id, int) else bigint_digits(list_id)
        definition = db.get(ListDefinition, internal_id) if internal_id is not None and 0 < internal_id < 2**63 else None
    else:
        import uuid

        from app.services import public_id_service

        try:
            public_id = uuid.UUID(str(list_id))
        except ValueError:
            public_id = None
        if public_id is not None and tenant_id is not None:
            definition = public_id_service.get_by_public_id(db, ListDefinition, public_id, tenant_id=tenant_id)
    if definition is not None and tenant_id is not None and definition.tenant_id != tenant_id:
        definition = None
    cache[cache_key] = definition
    return definition


def _key_or_none(definition: ListDefinition | None, key: Any) -> str | None:
    """Key einer existierenden Spalte; fremde/gelöschte Spalten -> None. Ohne auflösbare Liste
    bleibt der Key unverändert (nichts verwerfen, was sich nicht prüfen lässt)."""
    if definition is None:
        return None if key in (None, "") else str(key)
    column = resolve_column(definition, key)
    return column.key if column is not None else None


def normalize_config_column_keys(db, config: dict | None, *, tenant_id: int | None, cache: dict | None = None) -> dict | None:
    """Spalten-Keys einer Block-Konfiguration auf echte Spalten der verknüpften Liste bringen:
    alte Keys (feste Spalten vor Migration 0186, etwa von einem älteren Client oder Import) werden zum
    Key der Spalte, Keys fremder oder gelöschter Spalten zu None. Betrifft Gruppieren, Sortieren,
    Filtern und sichtbare Spalten (ganze Liste), die feste Spalte einer Listen-Zeile und die
    Quelle einer Matrix-Zeile. Listen-IDs sind hier interne IDs (block_config_ids)."""
    if not isinstance(config, dict):
        return config
    cache = {} if cache is None else cache
    result = dict(config)
    if result.get("linked_list_id") not in (None, ""):
        definition = _definition(db, result.get("linked_list_id"), tenant_id, cache)
        for field in _LIST_KEY_FIELDS:
            if result.get(field) not in (None, ""):
                result[field] = _key_or_none(definition, result[field])
        if isinstance(result.get("linked_list_visible_columns"), list):
            keys = [_key_or_none(definition, key) for key in result["linked_list_visible_columns"]]
            result["linked_list_visible_columns"] = list(dict.fromkeys(key for key in keys if key))
    auto_source = result.get("auto_source")
    auto_definition = (
        _definition(db, auto_source.get("list_id"), tenant_id, cache)
        if isinstance(auto_source, dict) and auto_source.get("type") == "list" else None
    )
    if isinstance(result.get("rows"), list):
        rows = []
        for row in result["rows"]:
            if not isinstance(row, dict):
                rows.append(row)
                continue
            row = dict(row)
            if row.get("auto_source_field") not in (None, ""):
                row["auto_source_field"] = _key_or_none(auto_definition, row["auto_source_field"])
            row_config = row.get("row_config")
            if isinstance(row_config, dict):
                row_definition = _definition(db, row.get("linked_list_id") or row_config.get("linked_list_id"), tenant_id, cache)
                for field in ("list_fixed_column", "list_value_column"):
                    if row_config.get(field) not in (None, ""):
                        row_config = {**row_config, field: _key_or_none(row_definition, row_config[field])}
                row["row_config"] = row_config
            rows.append(row)
        result["rows"] = rows
    return result


def _read_key(definition: ListDefinition | None, key: Any) -> Any:
    """Spalten-Key einer eingefrorenen Konfiguration für die Ausgabe: alter Key -> Key der
    Spalte (Liste existiert) bzw. synthetischer Key wie im hochgestuften Snapshot."""
    from app.services import list_legacy_adapter

    if not list_legacy_adapter.is_legacy_key(key):
        return key
    column = list_legacy_adapter.legacy_column(definition, key)
    return column.key if column is not None else f"legacy:{str(key).removeprefix('legacy:')}"


def upgrade_frozen_config(db, config: dict | None, *, tenant_id: int, cache: dict | None = None) -> dict | None:
    """Konfiguration eines Protokoll-Blocks für die Ausgabe ins aktuelle Format: Listen-Snapshots
    v1 -> v2 und alte Spalten-Keys passend dazu. Für abgeschlossene Protokolle, deren Daten
    eingefroren bleiben (offene stellt Migration 0187 um). Ändert nichts Gespeichertes."""
    from app.services import list_legacy_adapter

    if not isinstance(config, dict):
        return config
    cache = {} if cache is None else cache
    result = dict(config)
    definition = _definition(db, result.get("linked_list_id"), tenant_id, cache) if result.get("linked_list_id") not in (None, "") else None
    if isinstance(result.get("list_snapshot"), dict):
        result["list_snapshot"] = list_legacy_adapter.upgrade_list_snapshot(result["list_snapshot"], definition=definition)
    for field in _LIST_KEY_FIELDS:
        if result.get(field) not in (None, ""):
            result[field] = _read_key(definition, result[field])
    if isinstance(result.get("linked_list_visible_columns"), list):
        result["linked_list_visible_columns"] = [_read_key(definition, key) for key in result["linked_list_visible_columns"]]
    if isinstance(result.get("rows"), list):
        rows = []
        for row in result["rows"]:
            if not isinstance(row, dict):
                rows.append(row)
                continue
            row = dict(row)
            row_config = row.get("row_config") if isinstance(row.get("row_config"), dict) else {}
            row_list = row.get("linked_list_id") or row_config.get("linked_list_id")
            row_definition = _definition(db, row_list, tenant_id, cache) if row_list not in (None, "") else None
            if isinstance(row.get("list_snapshot"), dict):
                row["list_snapshot"] = list_legacy_adapter.upgrade_list_snapshot(row["list_snapshot"], definition=row_definition)
            for field in ("list_fixed_column", "list_value_column"):
                if row.get(field) not in (None, ""):
                    row[field] = _read_key(row_definition, row[field])
                if row_config.get(field) not in (None, ""):
                    row_config = {**row_config, field: _read_key(row_definition, row_config[field])}
            if row_config:
                row["row_config"] = row_config
            rows.append(row)
        result["rows"] = rows
    return result
