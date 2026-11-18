"""v1-Adapter für Listen mit festen zwei Spalten - die einzige Stelle im Anwendungscode, die die
alten Namen kennt (Semgrep-Regel ``.semgrep/no-legacy-list-columns.yml``).

Eingefrorene Daten behalten ihr Format: Listen-Snapshots abgeschlossener Protokolle
(``configuration_snapshot_json.list_snapshot`` bzw. ``row_config.list_snapshot``),
Zyklus-Backups (``table_snapshot`` der Tabellen list_definition/list_entry), alte
Mandanten-Exporte und Konfigurationen mit Spalten-Keys ``column_one``/``column_two``. Gelesen wird
alles über diese Funktionen, Anwendung und Frontend sehen nur das v2-Format:

    {"snapshot_version": 2, "synced_version": n,
     "columns": [{"id": "<key>", "title": "...", "value_type": "text", "sort_index": 10}],
     "label_column_id": "<key>" | None, "responsible_column_id": "<key>" | None,
     "entries": [{"id": 1, "sort_index": 0, "values": {"<key>": {...}}}],   # ganze Liste
     "entry_exists": true, "values": {"<key>": {...}},                      # eine Zeile
     "previous": {...} | None}

Spalten-Keys alter Daten: Existiert die Liste noch, die echten Keys ihrer Spalten mit
``legacy_key`` - so passen Snapshot und (bereits migrierte) Konfiguration zusammen. Sonst stabile
synthetische Keys ``legacy:column_one``/``legacy:column_two``.
"""
from __future__ import annotations

from typing import Any

LEGACY_KEYS = ("column_one", "column_two")
_SNAPSHOT_VERSION = 2


def legacy_column(definition: Any, key: str):
    """Spalte einer Liste zu einem alten Key ('column_one'/'column_two') oder einem synthetischen
    ('legacy:column_one'); None für alles andere."""
    if definition is None:
        return None
    legacy = key.removeprefix("legacy:")
    if legacy not in LEGACY_KEYS:
        return None
    return next((column for column in definition.columns if column.legacy_key == legacy), None)


def is_legacy_key(key: Any) -> bool:
    return isinstance(key, str) and key.removeprefix("legacy:") in LEGACY_KEYS


def _legacy_keys(definition: Any) -> dict[str, str]:
    keys = {legacy: f"legacy:{legacy}" for legacy in LEGACY_KEYS}
    if definition is not None:
        for column in definition.columns:
            if column.legacy_key in keys:
                keys[column.legacy_key] = column.key
    return keys


def _role(columns: list[dict[str, Any]], types: tuple[str, ...]) -> str | None:
    return next((column["id"] for column in columns if column["value_type"] in types), None)


def _values(item: dict[str, Any], keys: dict[str, str]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for legacy in LEGACY_KEYS:
        value = item.get(f"{legacy}_value")
        if isinstance(value, dict) and value:
            values[keys[legacy]] = dict(value)
    return values


def _strip_legacy(item: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in item.items() if not any(k.startswith(f"{legacy}_") for legacy in LEGACY_KEYS)}


def _upgrade_tracked(item: dict[str, Any], keys: dict[str, str]) -> dict[str, Any]:
    before = item.get("_tracked_before")
    if isinstance(before, dict) and any(f"{legacy}_value" in before for legacy in LEGACY_KEYS):
        item["_tracked_before"] = {"values": _values(before, keys)}
    return item


def is_v1_snapshot(snapshot: Any) -> bool:
    if not isinstance(snapshot, dict) or snapshot.get("snapshot_version") == _SNAPSHOT_VERSION:
        return False
    if any(f"{legacy}_title" in snapshot or f"{legacy}_value" in snapshot for legacy in LEGACY_KEYS):
        return True
    entries = snapshot.get("entries")
    return isinstance(entries, list) and any(
        isinstance(e, dict) and any(f"{legacy}_value" in e for legacy in LEGACY_KEYS) for e in entries
    )


def upgrade_list_snapshot(snapshot: Any, *, definition: Any = None) -> Any:
    """v1-Snapshot (ganze Liste oder eine Zeile) ins v2-Format; alles andere unverändert.
    Auch die Undo-Stufe ``previous`` und Änderungsmarkierungen (``_tracked_before``)."""
    if not is_v1_snapshot(snapshot):
        if isinstance(snapshot, dict) and isinstance(snapshot.get("previous"), dict) and is_v1_snapshot(snapshot["previous"]):
            return {**snapshot, "previous": upgrade_list_snapshot(snapshot["previous"], definition=definition)}
        return snapshot
    keys = _legacy_keys(definition)
    columns = [
        {"id": keys[legacy], "title": snapshot.get(f"{legacy}_title") or "", "value_type": snapshot.get(f"{legacy}_value_type") or "text",
         "sort_index": (index + 1) * 10}
        for index, legacy in enumerate(LEGACY_KEYS)
        if snapshot.get(f"{legacy}_title") is not None or snapshot.get(f"{legacy}_value_type") is not None
    ]
    upgraded = _strip_legacy(snapshot)
    upgraded["snapshot_version"] = _SNAPSHOT_VERSION
    upgraded["columns"] = columns
    # Rollen wie die Migration 0186: erste Text-/Termin-Spalte benennt, erste Personen-Spalte ist verantwortlich
    upgraded["label_column_id"] = _role(columns, ("text",)) or (columns[0]["id"] if columns else None)
    upgraded["responsible_column_id"] = _role(columns, ("participant", "participants"))
    if isinstance(snapshot.get("entries"), list):
        upgraded["entries"] = [
            _upgrade_tracked({**_strip_legacy(entry), "values": _values(entry, keys)}, keys) if isinstance(entry, dict) else entry
            for entry in snapshot["entries"]
        ]
    if any(f"{legacy}_value" in snapshot for legacy in LEGACY_KEYS) or "entry_exists" in snapshot:
        upgraded["values"] = _values(snapshot, keys)
    _upgrade_tracked(upgraded, keys)
    if isinstance(snapshot.get("previous"), dict):
        upgraded["previous"] = upgrade_list_snapshot(snapshot["previous"], definition=definition)
    return upgraded


def upgrade_table_snapshot_rows(table_name: str, rows: list[dict[str, Any]], *, columns_by_definition: dict[int, list[dict[str, Any]]] | None = None) -> list[dict[str, Any]]:
    """Zeilen eines Zyklus-Backups (table_snapshot) von list_definition/list_entry ins aktuelle
    Format. ``list_entry``-Zeilen bekommen ``values_json`` aus den alten Wertfeldern; die Keys
    kommen aus ``columns_by_definition`` (synthetisch, siehe ``table_snapshot_list_columns``)."""
    if table_name == "list_entry":
        result = []
        for row in rows:
            if "values_json" in row or not any(f"{legacy}_value_json" in row for legacy in LEGACY_KEYS):
                result.append(row)
                continue
            keys = {column["legacy_key"]: column["key"] for column in (columns_by_definition or {}).get(row.get("list_definition_id"), []) if column.get("legacy_key")}
            values = {}
            for legacy in LEGACY_KEYS:
                value = row.get(f"{legacy}_value_json")
                if isinstance(value, dict) and value and legacy in keys:
                    values[keys[legacy]] = dict(value)
            result.append({**_strip_legacy(row), "values_json": values})
        return result
    if table_name == "list_definition":
        return [_strip_legacy(row) if any(f"{legacy}_title" in row for legacy in LEGACY_KEYS) else row for row in rows]
    return rows


def table_snapshot_list_columns(definition_rows: list[dict[str, Any]], *, live_keys: dict[int, dict[str, str]] | None = None) -> dict[int, list[dict[str, Any]]]:
    """Spalten zu alten list_definition-Zeilen eines Zyklus-Backups (vor 0186 gab es keine
    list_column-Zeilen darin). Keys der noch existierenden Spalten (``live_keys``: Liste ->
    legacy_key -> Key), sonst synthetisch."""
    result: dict[int, list[dict[str, Any]]] = {}
    for row in definition_rows:
        if not any(f"{legacy}_title" in row for legacy in LEGACY_KEYS):
            continue
        definition_id = row.get("id")
        live = (live_keys or {}).get(definition_id, {})
        result[definition_id] = [
            {"key": live.get(legacy, f"legacy:{legacy}"), "legacy_key": legacy, "list_definition_id": definition_id,
             "title": row.get(f"{legacy}_title") or "", "value_type": row.get(f"{legacy}_value_type") or "text", "sort_index": (index + 1) * 10}
            for index, legacy in enumerate(LEGACY_KEYS)
        ]
    return result


def upgrade_config_column_key(definition: Any, key: Any) -> Any:
    """Spalten-Key einer Konfiguration: alter Key -> echter Key der Liste (oder None, wenn die
    Liste die Spalte nicht mehr hat). Neue Keys bleiben unverändert."""
    if not is_legacy_key(key):
        return key
    column = legacy_column(definition, key)
    return column.key if column is not None else None


def legacy_value_fields(holder: Any, suffix: str = "_value") -> list[str]:
    """Namen der alten Wertfelder in einem Eintrag/Snapshot/Backup-Zeile (``_value`` in
    Snapshots, ``_value_json`` in table_snapshot-Zeilen), damit Code, der IDs übersetzt, beide
    Formate bedienen kann, ohne die Namen selbst zu kennen."""
    if not isinstance(holder, dict):
        return []
    return [f"{legacy}{suffix}" for legacy in LEGACY_KEYS if f"{legacy}{suffix}" in holder]


def legacy_value_types(snapshot: Any) -> dict[str, str]:
    """Wertfeld -> Spaltentyp eines v1-Snapshots (leer bei v2)."""
    if not isinstance(snapshot, dict):
        return {}
    return {f"{legacy}_value": str(snapshot.get(f"{legacy}_value_type") or "text") for legacy in LEGACY_KEYS}
