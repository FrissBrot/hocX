"""Formprüfung der Blockkonfiguration beim Speichern (Nachtlauf 2026-11-25, protokolle/eingaben).

``ProtocolElementBlockUpdate.configuration_snapshot_json`` ist ein freies ``dict``. Die Leser
(Mitgliederabgleich beim Laden der Elemente, Antwortaufbau, PDF-Export) erwarten bei den
bekannten Schlüsseln aber feste Formen: ``attendance_entries: 5`` wurde gespeichert, danach
scheiterte ``GET /protocols/{id}/elements`` für alle Personen dauerhaft mit 500, ebenso der
PDF-Export (Abschliessen). Andere Formfehler (``rows: 5``, Zahlen über BIGINT) liessen schon den
PATCH mit 500 und einem Eintrag im Fehlerprotokoll scheitern.

Geprüft wird nur die Form, nicht der Inhalt: bekannte Listen sind Listen (bei Zeilen/Spalten/
Einträgen aus Objekten), bekannte Objekte sind Objekte, Texte sind Texte; Zahlen passen in eine
BIGINT-Spalte, Texte enthalten kein NUL (PostgreSQL-JSONB lehnt es ab), die Verschachtelung ist
begrenzt. Was der Editor speichert, erfüllt das immer.
"""

from __future__ import annotations

from typing import Any

_MAX_BIGINT = 2**63 - 1
_MAX_DEPTH = 40

# Listen, deren Einträge Objekte sind (die Leser greifen mit .get() darauf zu)
_LISTS_OF_OBJECTS = ("rows", "columns", "attendance_entries", "entries", "event_fields")
# Listen mit beliebigen Einträgen
_LISTS = ("bullet_items", "attendance_excluded_participant_ids")
_OBJECTS = ("auto_source",)
_TEXTS = ("selected_date", "selected_time", "session_label")
# Der Mitgliederabgleich liest diese Schlüssel mit config.get(key, []) - null bricht dort ab
_NOT_NULL = ("attendance_entries", "entries")


class BlockConfigShapeError(ValueError):
    """Erwartet: Konfiguration hat nicht die Form, die der Editor speichert."""


def _check_values(value: Any, depth: int) -> None:
    if depth > _MAX_DEPTH:
        raise BlockConfigShapeError("configuration too deeply nested")
    if isinstance(value, bool) or value is None or isinstance(value, float):
        return
    if isinstance(value, int):
        if abs(value) > _MAX_BIGINT:
            raise BlockConfigShapeError("number out of range")
        return
    if isinstance(value, str):
        if "\x00" in value:
            raise BlockConfigShapeError("text contains NUL")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _check_values(key, depth + 1)
            _check_values(item, depth + 1)
        return
    if isinstance(value, list):
        for item in value:
            _check_values(item, depth + 1)


def check_block_config_shape(config: dict) -> None:
    """Wirft ``BlockConfigShapeError``, wenn ``config`` nicht die erwartete Form hat."""
    for key in _NOT_NULL:
        if key in config and config[key] is None:
            raise BlockConfigShapeError(f"{key} must not be null")
    for key in _LISTS_OF_OBJECTS:
        value = config.get(key)
        if value is not None and (not isinstance(value, list) or not all(isinstance(item, dict) for item in value)):
            raise BlockConfigShapeError(f"{key} must be a list of objects")
    for item in (config.get("rows") or []) + (config.get("columns") or []):
        # Matrix-Zeilen werden im Export nach sort_index sortiert: Text neben Zahl bricht dort ab
        sort_index = item.get("sort_index")
        if sort_index is not None and (isinstance(sort_index, bool) or not isinstance(sort_index, (int, float))):
            raise BlockConfigShapeError("sort_index must be a number")
    for row in config.get("rows") or []:
        if row.get("row_config") is not None and not isinstance(row["row_config"], dict):
            raise BlockConfigShapeError("row_config must be an object")
    for key in _LISTS:
        value = config.get(key)
        if value is not None and not isinstance(value, list):
            raise BlockConfigShapeError(f"{key} must be a list")
    for key in _OBJECTS:
        value = config.get(key)
        if value is not None and not isinstance(value, dict):
            raise BlockConfigShapeError(f"{key} must be an object")
    for key in _TEXTS:
        value = config.get(key)
        if value is not None and not isinstance(value, str):
            raise BlockConfigShapeError(f"{key} must be a text")
    _check_values(config, 0)


def bigint_digits(value: str) -> int | None:
    """Ziffernfolge als Zahl, wenn sie eine interne id sein kann (nur ASCII-Ziffern, BIGINT).
    ``str.isdigit()`` allein nimmt auch «²» an, woran ``int()`` scheitert."""
    if value.isascii() and value.isdigit():
        number = int(value)
        if number <= _MAX_BIGINT:
            return number
    return None
