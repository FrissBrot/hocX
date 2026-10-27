"""Modus «Einfach» des Dokument-Designers: welche Bausteine er kennt und welche 1–3
Einstellungen er je Baustein in Alltagssprache zeigt.

Der Einfach-Modus bearbeitet dieselbe Vorlage wie «Erweitert» (layout.TemplateContent), nur
über diese Beschreibung: Ein Baustein ist ein Knoten der obersten Ebene des Inhalts; der erste
passende Eintrag in ``SIMPLE_BLOCKS`` bestimmt Namen und Einstellungen. Knoten ohne Eintrag
erscheinen als «Eigener Bereich» (Ein/Aus und Reihenfolge, Rest im Modus «Erweitert»).

Arten von Einstellungen (Pfade mit Punkt, relativ zum Knoten):
- ``toggle``: boolescher Wert an ``path`` (``default``, wenn das Feld fehlt)
- ``variant``: Darstellung einer Elementart (``appearance``) für diesen Block
- ``text``: Text (TextContent) an ``path``, nur solange er aus reinem Text besteht
- ``markdown``: Fliesstext (rich_text) an ``path``
- ``names``: Unterschriften ``[{label, name}]`` an ``path``
- ``multi``: Mehrfachauswahl aus ``options`` an ``path``
- ``image``: Bild aus der Bibliothek (Quelle an ``path``)
- ``condition``: fertige Bedingung aus ``CONDITION_PRESETS`` als ``visible_if``

Texte (Namen, Beschriftungen, Hilfen) übersetzt das Frontend:
``documentStudio.simple.block.<key>`` und ``documentStudio.simple.setting.<block>.<setting>``.
"""
from __future__ import annotations

from typing import Any

from app.documents.appearance import APPEARANCE_VARIANTS, DESIGN_KEYS

# «Nur zeigen, wenn …»: fertige Bedingungen statt eines freien Regel-Editors
CONDITION_PRESETS: dict[str, dict[str, Any]] = {
    "open_todos": {"op": "count", "path": "todos.open", "cmp": "gt", "value": 0},
    "protocol_open_todos": {"op": "count", "path": "protocol.open_todos", "cmp": "gt", "value": 0},
    "upcoming_events": {"op": "count", "path": "events.upcoming", "cmp": "gt", "value": 0},
}

_ONLY_IF_ANY = {"key": "only_if_any", "kind": "toggle", "path": "hide_if_empty", "default": True}


def _variant(kind: str) -> dict[str, Any]:
    return {"key": "style", "kind": "variant", "appearance": kind, "options": list(APPEARANCE_VARIANTS[kind])}


SIMPLE_BLOCKS: list[dict[str, Any]] = [
    {
        "key": "protocol",
        "match": {"type": "data_block", "component": ["protocol_element"]},
        "settings": [
            {"key": "session_todos", "kind": "toggle", "path": "params.include_session_todos", "default": True},
            {"key": "images", "kind": "toggle", "path": "params.include_images", "default": True},
            {"key": "titles_only", "kind": "toggle", "path": "params.titles_only", "default": False},
        ],
    },
    {"key": "todos", "match": {"type": "data_block", "component": ["todo_table"]}, "settings": [_ONLY_IF_ANY, _variant("todo")]},
    {"key": "attendance", "match": {"type": "data_block", "component": ["attendance"]}, "settings": [_variant("attendance")]},
    {"key": "session_date", "match": {"type": "data_block", "component": ["session_date"]}, "settings": [_variant("session_date")]},
    {
        "key": "signatures",
        "match": {"type": "data_block", "component": ["signature_fields"]},
        "settings": [
            {"key": "names", "kind": "names", "path": "params.fields"},
            {"key": "place_date", "kind": "toggle", "path": "params.with_place_date", "default": True},
        ],
    },
    {"key": "events", "match": {"type": "data_block", "component": ["event_table", "event_agenda", "event_calendar_month"]}, "settings": [_ONLY_IF_ANY]},
    {"key": "balance", "match": {"type": "data_block", "component": ["finance_balance"]}, "settings": [_variant("finance_balance")]},
    {"key": "kpis", "match": {"type": "data_block", "component": ["kpi_tiles"]}, "settings": [_variant("kpi_tiles")]},
    {"key": "data", "match": {"type": "data_block"}, "settings": [_ONLY_IF_ANY]},
    {"key": "verify", "match": {"type": "verify_note"}, "settings": [{"key": "qr", "kind": "toggle", "path": "show_qr", "default": False}]},
    {
        "key": "metadata",
        "match": {"type": "metadata"},
        "settings": [{"key": "fields", "kind": "multi", "path": "fields", "options": ["number", "date", "status", "version", "place"], "default": ["number", "date", "status", "version"]}],
    },
    {"key": "title", "match": {"type": "text", "role": ["title"]}, "settings": [{"key": "text", "kind": "text", "path": "content"}]},
    {"key": "subtitle", "match": {"type": "text", "role": ["subtitle"]}, "settings": [{"key": "text", "kind": "text", "path": "content"}]},
    {"key": "heading", "match": {"type": "text", "role": ["heading"]}, "settings": [{"key": "text", "kind": "text", "path": "content"}]},
    {"key": "text", "match": {"type": "text"}, "settings": [{"key": "text", "kind": "text", "path": "content"}]},
    {"key": "rich_text", "match": {"type": "rich_text"}, "settings": [{"key": "text", "kind": "markdown", "path": "markdown"}]},
    {"key": "image", "match": {"type": "image"}, "settings": [{"key": "image", "kind": "image", "path": "source"}]},
    {"key": "toc", "match": {"type": "toc"}, "settings": []},
    {"key": "divider", "match": {"type": "divider"}, "settings": []},
    {"key": "page_break", "match": {"type": "page_break"}, "settings": []},
    {"key": "spacer", "match": {"type": "spacer"}, "settings": []},
    {"key": "list", "match": {"type": "list"}, "settings": []},
    {"key": "table", "match": {"type": "table"}, "settings": []},
    {"key": "qr_code", "match": {"type": "qr_code"}, "settings": []},
    {"key": "page_number", "match": {"type": "page_number"}, "settings": []},
    # Abschnitte und Kästen: nur die fertige Bedingung, Inhalt im Modus «Erweitert»
    {"key": "group", "match": {"type": ["section", "container", "stack", "row", "column", "grid"]}, "settings": [{"key": "condition", "kind": "condition"}]},
]

# «+ Baustein hinzufügen»: häufige Bausteine (Schlüssel der Bibliothek, components.LIBRARY)
SIMPLE_ADD: list[str] = ["text", "heading", "events_table", "finance_balance", "image", "divider", "signatures", "page_break"]


def simple_payload() -> dict[str, Any]:
    """Für den Katalog des Designers (components.catalog_payload)."""
    return {
        "blocks": SIMPLE_BLOCKS,
        "add": SIMPLE_ADD,
        "styles": list(DESIGN_KEYS),
        "conditions": CONDITION_PRESETS,
    }
