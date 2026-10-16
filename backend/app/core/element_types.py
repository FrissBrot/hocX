"""Zugriff auf die Elementtyp-Registry (generiert aus element-types/registry.json).

Ersetzt die früher verstreuten id→Code-/id→Render-Typ-Tabellen. Neue Typen oder geänderte
Fähigkeiten nur in element-types/registry.json eintragen und
`python3 scripts/sync-element-types.py` ausführen.
"""
from __future__ import annotations

from app.core.element_types_generated import ELEMENT_TYPES

_BY_ID: dict[int, dict] = {entry["id"]: entry for entry in ELEMENT_TYPES}
_BY_CODE: dict[str, dict] = {entry["code"]: entry for entry in ELEMENT_TYPES}

# Vorgabe für unbekannte ids (sollte nach der Validierung in element_config.py nicht vorkommen).
_FALLBACK = _BY_CODE["text"]


def element_type(element_type_id: int | str | None) -> dict:
    try:
        return _BY_ID.get(int(element_type_id or 0), _FALLBACK)
    except (TypeError, ValueError):
        return _FALLBACK


def is_known_element_type(element_type_id: int | str | None) -> bool:
    try:
        return int(element_type_id or 0) in _BY_ID
    except (TypeError, ValueError):
        return False


def element_type_code(element_type_id: int | str | None) -> str:
    return element_type(element_type_id)["code"]


def element_type_id_for_code(code: str) -> int | None:
    entry = _BY_CODE.get(code)
    return entry["id"] if entry else None


def render_type_id(element_type_id: int | str | None) -> int:
    return element_type(element_type_id)["render_type_id"]


def allows_multiple_values(element_type_id: int | str | None) -> bool:
    return bool(element_type(element_type_id)["allows_multiple_values"])


def supports_repeat(element_type_id: int | str | None, source: str) -> bool:
    return source in element_type(element_type_id)["repeat"]
