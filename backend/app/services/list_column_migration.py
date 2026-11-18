"""Umstellung gespeicherter Konfigurationen auf Spalten-Keys (Migration 0187_list_column_config_keys).

Reine Funktionen ohne Datenbank: die Migration lädt je Liste die Zuordnung alter Key -> neuer Key
(``list_column.legacy_key`` -> ``list_column.key``) und schreibt damit jede Live-Konfiguration um.
Getestet in tests/test_list_column_migration.py. Eingefrorene Daten abgeschlossener Protokolle
bleiben unverändert (Adapter beim Lesen, list_legacy_adapter.py).

Betroffen:
- Block-Konfigurationen (Bausteine, Vorlagen-Traktanden und -Blöcke, offene Protokoll-Blöcke):
  ``linked_list_group_by``, ``linked_list_sort_by``, ``linked_list_filter_column`` (Liste
  ``linked_list_id``), ``rows[].row_config.list_fixed_column`` (Liste der Zeile),
  ``rows[].auto_source_field`` (Liste ``auto_source.list_id``); in offenen Protokollen zusätzlich
  die Listen-Snapshots (v1 -> v2).
- Dokumentvorlagen: Parameter ``group_by``, ``sort_by``, ``filter_column`` neben ``list_id``.
- Abgaben: ``submission_assignment.responsible_participant_source`` bei Quelle «Liste».
"""
from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Callable

from app.services import list_legacy_adapter

# Liste (interne ID als int oder public_id als Text) -> {legacy_key: neuer Key}
KeyMap = dict[Any, dict[str, str]]

_BLOCK_FIELDS = ("linked_list_group_by", "linked_list_sort_by", "linked_list_filter_column")
_STUDIO_FIELDS = ("group_by", "sort_by", "filter_column")


@dataclass
class Report:
    rewritten: int = 0
    nulled: int = 0
    snapshots: int = 0
    unknown_lists: set = field(default_factory=set)

    def line(self, table: str) -> str:
        return (
            f"0187 {table}: {self.rewritten} Spalten-Keys umgeschrieben, {self.nulled} entfernt "
            f"(Liste/Spalte fehlt), {self.snapshots} Snapshots hochgestuft"
        )


def _lookup(key_map: KeyMap, list_ref: Any) -> dict[str, str] | None:
    if list_ref in (None, "") or isinstance(list_ref, bool):
        return None
    for candidate in (list_ref, str(list_ref).lower()):
        if candidate in key_map:
            return key_map[candidate]
    try:
        return key_map.get(int(list_ref))
    except (TypeError, ValueError):
        return None


def _convert(value: Any, keys: dict[str, str] | None, report: Report, list_ref: Any) -> Any:
    if not list_legacy_adapter.is_legacy_key(value):
        return value
    legacy = str(value).removeprefix("legacy:")
    if keys is None:
        report.unknown_lists.add(str(list_ref))
        report.nulled += 1
        return None
    new_key = keys.get(legacy)
    if new_key is None:
        report.nulled += 1
        return None
    report.rewritten += 1
    return new_key


def _definition(keys: dict[str, str] | None):
    """Minimales Listenobjekt für den Snapshot-Adapter (nur Spalten mit legacy_key/key)."""
    if keys is None:
        return None
    return SimpleNamespace(columns=[SimpleNamespace(legacy_key=legacy, key=key) for legacy, key in keys.items()])


def rewrite_block_config(config: Any, key_map: KeyMap, report: Report, *, upgrade_snapshots: bool = False) -> Any:
    if not isinstance(config, dict):
        return config
    result = dict(config)
    list_ref = result.get("linked_list_id")
    keys = _lookup(key_map, list_ref)
    for name in _BLOCK_FIELDS:
        if name in result:
            result[name] = _convert(result[name], keys, report, list_ref)
    if upgrade_snapshots and list_legacy_adapter.is_v1_snapshot(result.get("list_snapshot")):
        result["list_snapshot"] = list_legacy_adapter.upgrade_list_snapshot(result["list_snapshot"], definition=_definition(keys))
        report.snapshots += 1
    auto_source = result.get("auto_source")
    auto_ref = auto_source.get("list_id") if isinstance(auto_source, dict) and auto_source.get("type") == "list" else None
    auto_keys = _lookup(key_map, auto_ref)
    if isinstance(result.get("rows"), list):
        rows = []
        for row in result["rows"]:
            if not isinstance(row, dict):
                rows.append(row)
                continue
            row = dict(row)
            if "auto_source_field" in row:
                row["auto_source_field"] = _convert(row["auto_source_field"], auto_keys, report, auto_ref)
            row_config = row.get("row_config")
            row_ref = row.get("linked_list_id") or (row_config.get("linked_list_id") if isinstance(row_config, dict) else None)
            row_keys = _lookup(key_map, row_ref)
            if isinstance(row_config, dict) and "list_fixed_column" in row_config:
                row["row_config"] = {**row_config, "list_fixed_column": _convert(row_config["list_fixed_column"], row_keys, report, row_ref)}
            if "list_fixed_column" in row:
                row["list_fixed_column"] = _convert(row["list_fixed_column"], row_keys, report, row_ref)
            if upgrade_snapshots and list_legacy_adapter.is_v1_snapshot(row.get("list_snapshot")):
                row["list_snapshot"] = list_legacy_adapter.upgrade_list_snapshot(row["list_snapshot"], definition=_definition(row_keys))
                report.snapshots += 1
            rows.append(row)
        result["rows"] = rows
    return result


def rewrite_element_definition(config: Any, key_map: KeyMap, report: Report) -> Any:
    if not isinstance(config, dict) or not isinstance(config.get("blocks"), list):
        return config
    blocks = []
    for block in config["blocks"]:
        if isinstance(block, dict) and isinstance(block.get("configuration_json"), dict):
            block = {**block, "configuration_json": rewrite_block_config(block["configuration_json"], key_map, report)}
        blocks.append(block)
    return {**config, "blocks": blocks}


def rewrite_studio_params(value: Any, key_map: KeyMap, report: Report) -> Any:
    """Dokumentvorlagen: jedes Objekt mit ``list_id`` und Spalten-Parametern (beliebig tief)."""
    if isinstance(value, list):
        return [rewrite_studio_params(item, key_map, report) for item in value]
    if not isinstance(value, dict):
        return value
    result = {key: rewrite_studio_params(item, key_map, report) for key, item in value.items()}
    if "list_id" in result and any(name in result for name in _STUDIO_FIELDS):
        keys = _lookup(key_map, result.get("list_id"))
        for name in _STUDIO_FIELDS:
            if name in result:
                converted = _convert(result[name], keys, report, result.get("list_id"))
                result[name] = "" if converted is None else converted
    return result


def rewrite_responsible_source(source: Any, keys: dict[str, str] | None, report: Report, list_ref: Any) -> Any:
    return _convert(source, keys, report, list_ref)


def rewrite_rows(rows: list[tuple[Any, Any]], rewrite: Callable[[Any], Any]) -> list[tuple[Any, Any]]:
    """(id, alter Wert) -> nur die geänderten (id, neuer Wert)."""
    changed = []
    for row_id, value in rows:
        new_value = rewrite(value)
        if new_value != value:
            changed.append((row_id, new_value))
    return changed
