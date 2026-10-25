"""Komponentenbibliothek des Visual Designers (eine Quelle für Backend und Frontend).

Zwei Ebenen:

- **Knotentypen** (``NODE_TYPES``): Editor-Metadaten je Layoutknoten aus layout.py - Kategorie,
  ab welchem Bearbeitungsmodus der Typ angeboten wird, ob er Kinder hat und welche
  Eigenschaftsgruppen das Eigenschaftenpanel zeigt. Parameterschema = Pydantic-Modell des
  Knotens (``model_json_schema``), Darstellung = typst/layout.typ.
- **Bibliothekseinträge** (``LIBRARY``): Vorbelegte Knoten, wie sie Benutzer in der linken
  Seitenleiste sehen («Dokumenttitel», «Aufgaben», «Unterschriften» …). Ein Eintrag ist ein
  gültiger Knoten (mit Bindungen bzw. Fachkomponente); beim Einfügen vergibt der Designer neue
  IDs. Fachkomponenten kommen aus dem Katalog (catalog.py) und tragen dessen Recht.

Bezeichnungen und Hilfetexte stehen in frontend/messages/<locale>/documentStudio.json
(``nodeType.<typ>``, ``library.<schlüssel>.label/help``).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from app.documents.catalog import CATALOG, NEEDS_PROTOCOL
from app.documents.layout import CONTAINER_TYPES, MASTER_ONLY_TYPES, NODE_MODELS

Mode = Literal["simple", "advanced", "expert"]
MODES: tuple[Mode, ...] = ("simple", "advanced", "expert")


@dataclass(frozen=True)
class NodeTypeMeta:
    category: Literal["layout", "content", "document", "data"]
    mode: Mode
    groups: tuple[str, ...]
    icon: str


_BOX = ("size", "spacing", "background", "border", "align")
_TEXT = ("typography",)
_LOGIC = ("visibility", "repeat", "pagination")

NODE_TYPES: dict[str, NodeTypeMeta] = {
    "stack": NodeTypeMeta("layout", "advanced", (*_BOX, *_TEXT, *_LOGIC, "stack"), "stack"),
    "row": NodeTypeMeta("layout", "advanced", (*_BOX, *_LOGIC, "row"), "columns"),
    "column": NodeTypeMeta("layout", "advanced", (*_BOX, *_TEXT, *_LOGIC, "stack"), "column"),
    "grid": NodeTypeMeta("layout", "advanced", (*_BOX, *_LOGIC, "grid"), "grid"),
    "container": NodeTypeMeta("layout", "advanced", (*_BOX, *_TEXT, *_LOGIC, "container"), "box"),
    "section": NodeTypeMeta("layout", "simple", (*_BOX, *_TEXT, *_LOGIC, "section"), "section"),
    "absolute_layer": NodeTypeMeta("layout", "expert", ("spacing", *_LOGIC, "layer"), "layers"),
    "text": NodeTypeMeta("content", "simple", ("content", *_BOX, *_TEXT, *_LOGIC), "text"),
    "rich_text": NodeTypeMeta("content", "simple", ("content", *_BOX, *_TEXT, *_LOGIC), "richtext"),
    "image": NodeTypeMeta("content", "simple", ("image", *_BOX, *_LOGIC), "image"),
    "divider": NodeTypeMeta("content", "simple", ("divider", "spacing", "visibility"), "divider"),
    "spacer": NodeTypeMeta("content", "simple", ("spacer", "visibility"), "spacer"),
    "table": NodeTypeMeta("content", "advanced", ("table", *_BOX, *_TEXT, *_LOGIC), "table"),
    "list": NodeTypeMeta("content", "simple", ("list", *_BOX, *_TEXT, *_LOGIC), "list"),
    "qr_code": NodeTypeMeta("content", "advanced", ("qr", *_BOX, "visibility"), "qr"),
    "page_break": NodeTypeMeta("document", "simple", ("pagebreak", "visibility"), "pagebreak"),
    "header": NodeTypeMeta("document", "advanced", (*_BOX, *_TEXT), "header"),
    "footer": NodeTypeMeta("document", "advanced", (*_BOX, *_TEXT), "footer"),
    "page_number": NodeTypeMeta("document", "simple", ("pagenumber", *_BOX, *_TEXT, "visibility"), "pagenumber"),
    "toc": NodeTypeMeta("document", "simple", ("toc", *_BOX, *_TEXT, "visibility"), "toc"),
    "verify_note": NodeTypeMeta("document", "advanced", ("verify", *_BOX, *_TEXT, "visibility"), "verify"),
    "metadata": NodeTypeMeta("document", "simple", ("metadata", *_BOX, *_TEXT, "visibility"), "metadata"),
    "watermark": NodeTypeMeta("document", "advanced", ("watermark", "visibility"), "watermark"),
    "data_block": NodeTypeMeta("data", "simple", ("data", *_BOX, *_TEXT, *_LOGIC), "data"),
    "component_ref": NodeTypeMeta("layout", "advanced", ("component", "spacing", "visibility", "pagination"), "component"),
}

assert set(NODE_TYPES) == set(NODE_MODELS), "Jeder Knotentyp braucht Editor-Metadaten"


@dataclass(frozen=True)
class LibraryEntry:
    key: str
    group: str
    mode: Mode
    node: dict[str, Any]
    # Nur in Seitenvorlagen (Kopf/Fuss/Hintergrund) einfügbar
    master_only: bool = False
    access: str = "reader"
    needs_protocol: bool = False
    tags: tuple[str, ...] = field(default_factory=tuple)


def _t(*inlines: dict[str, Any]) -> dict[str, Any]:
    return {"default": list(inlines)}


def _bind(path: str, **fmt: Any) -> dict[str, Any]:
    return {"t": "bind", "path": path, **({"format": fmt} if fmt else {})}


def _key(key: str) -> dict[str, Any]:
    return {"t": "key", "key": key}


def _data(component: str, **extra: Any) -> dict[str, Any]:
    return {"type": "data_block", "component": component, **extra}


_GENERAL: list[LibraryEntry] = [
    LibraryEntry("heading", "general", "simple", {"type": "text", "role": "heading", "level": 1, "content": _t({"t": "text", "v": ""})}),
    LibraryEntry("text", "general", "simple", {"type": "text", "role": "paragraph", "content": _t({"t": "text", "v": ""})}),
    LibraryEntry("rich_text", "general", "simple", {"type": "rich_text", "markdown": ""}),
    LibraryEntry("image", "general", "simple", {"type": "image", "source": {"kind": "asset", "asset_id": None}, "style": {"width": "60mm"}}),
    LibraryEntry("image_gallery", "general", "advanced", _data("image_gallery", params={"columns": 2})),
    LibraryEntry("table", "general", "advanced", {"type": "table", "columns": [{"header": _t({"t": "text", "v": ""})}, {"header": _t({"t": "text", "v": ""})}], "rows": [["", ""], ["", ""]]}),
    LibraryEntry("list", "general", "simple", {"type": "list", "items": [""]}),
    LibraryEntry("divider", "general", "simple", {"type": "divider"}),
    LibraryEntry("spacer", "general", "simple", {"type": "spacer", "size": 6}),
    LibraryEntry("qr_code", "general", "advanced", {"type": "qr_code", "target": "url", "url": "https://"}),
    LibraryEntry("page_break", "general", "simple", {"type": "page_break"}),
    LibraryEntry("container", "general", "advanced", {"type": "container", "style": {"padding": {"top": 4, "right": 4, "bottom": 4, "left": 4}, "background": "$brand.surface", "border": {"width": 0.5, "radius": 2}}, "children": []}),
    LibraryEntry("section", "general", "simple", {"type": "section", "title": _t({"t": "text", "v": ""}), "children": []}),
    LibraryEntry("columns_2", "general", "advanced", {"type": "row", "children": [{"type": "column", "style": {"width": "1fr"}, "children": []}, {"type": "column", "style": {"width": "1fr"}, "children": []}]}),
    LibraryEntry("columns_3", "general", "advanced", {"type": "row", "children": [{"type": "column", "style": {"width": "1fr"}, "children": []}, {"type": "column", "style": {"width": "1fr"}, "children": []}, {"type": "column", "style": {"width": "1fr"}, "children": []}]}),
    LibraryEntry("grid", "general", "expert", {"type": "grid", "columns": 2, "children": []}),
    LibraryEntry("absolute_layer", "general", "expert", {"type": "absolute_layer", "anchor": "flow", "height": 60, "children": []}),
]

_DOCUMENT: list[LibraryEntry] = [
    LibraryEntry("document_title", "document", "simple", {"type": "text", "role": "title", "content": _t(_bind("document.title"))}),
    LibraryEntry("subtitle", "document", "simple", {"type": "text", "role": "subtitle", "content": _t(_bind("document.subtitle"))}),
    LibraryEntry("metadata", "document", "simple", {"type": "metadata"}),
    LibraryEntry("document_number", "document", "simple", {"type": "text", "role": "small", "content": _t(_key("titlePage.number"), {"t": "text", "v": ": "}, _bind("document.number"))}),
    LibraryEntry("date", "document", "simple", {"type": "text", "role": "paragraph", "content": _t(_bind("document.date", date="long"))}),
    LibraryEntry("version", "document", "simple", {"type": "text", "role": "small", "content": _t(_key("titlePage.version"), {"t": "text", "v": ": "}, _bind("document.version"))}),
    LibraryEntry("toc", "document", "simple", {"type": "toc"}),
    LibraryEntry("page_number", "document", "simple", {"type": "page_number"}),
    LibraryEntry("verify_note", "document", "advanced", {"type": "verify_note", "show_qr": True}),
    LibraryEntry("logo", "document", "simple", {"type": "image", "source": {"kind": "binding", "path": "brand.logo"}, "style": {"width": "40mm"}}),
    LibraryEntry("organization", "document", "simple", {"type": "stack", "gap": 0.5, "children": [
        {"type": "text", "role": "label", "content": _t(_bind("organization.name"))},
        {"type": "text", "role": "small", "content": _t(_bind("organization.address"))},
    ]}),
    LibraryEntry("header", "document", "advanced", {"type": "header", "children": [{"type": "row", "children": [
        {"type": "text", "role": "small", "content": _t(_bind("document.title")), "style": {"width": "fill"}},
        {"type": "text", "role": "small", "content": _t(_bind("document.date"))},
    ]}, {"type": "divider", "thickness": 0.4}]}, master_only=True),
    LibraryEntry("footer", "document", "advanced", {"type": "footer", "children": [{"type": "row", "children": [
        {"type": "text", "role": "small", "content": _t(_bind("document.number")), "style": {"width": "fill"}},
        {"type": "page_number"},
    ]}]}, master_only=True),
    LibraryEntry("watermark", "document", "advanced", {"type": "watermark"}, master_only=True),
]


def _component_entries() -> list[LibraryEntry]:
    presets: list[tuple[str, str, dict[str, Any]]] = [
        ("session_info", "session_date", {}),
        ("protocol_sections", "protocol_element", {}),
        ("agenda_items", "protocol_element", {"params": {"titles_only": True, "invitation_only": True}}),
        ("decisions", "protocol_element", {"params": {"content": "text", "include_session_todos": False, "include_images": False}}),
        ("session_notes", "session_notes", {}),
        ("matrix", "matrix", {}),
        ("tasks", "todo_table", {"title_mode": "auto"}),
        ("attendance", "attendance", {"title_mode": "auto"}),
        ("attendance_matrix", "attendance_matrix", {"title_mode": "auto"}),
        ("attendance_sheet", "attendance_sheet", {}),
        ("members", "member_list", {"title_mode": "auto"}),
        ("entry_exit", "entry_exit", {"title_mode": "auto"}),
        ("events_agenda", "event_agenda", {"params": {"event_filter": {"range": {"mode": "future"}}}}),
        ("events_table", "event_table", {"params": {"event_filter": {"range": {"mode": "future"}}}}),
        ("calendar", "event_calendar_month", {"params": {"event_filter": {"range": {"mode": "window", "start_days": 0, "end_days": 31}}}}),
        ("list_table", "list_table", {}),
        ("finance_balance", "finance_balance", {"title_mode": "auto"}),
        ("finance_transactions", "finance_transactions", {"params": {"relative": "current_year"}}),
        ("fines", "fines", {"title_mode": "auto"}),
        ("statistics_kpis", "kpi_tiles", {"params": {"relative": "current_year"}}),
        ("statistics_table", "stat_table", {"params": {"relative": "current_year"}}),
        ("chart", "chart", {"params": {"relative": "current_year"}, "keep_together": True}),
        ("form", "form", {"params": {"rows": [{"label": "", "value": ""}]}}),
        ("signatures", "signature_fields", {}),
        ("protocol_image", "image", {}),
    ]
    entries = []
    for key, component, extra in presets:
        entry = CATALOG[component]
        entries.append(
            LibraryEntry(key, f"data_{entry.group}", "simple", _data(component, **extra), access=entry.access, needs_protocol=component in NEEDS_PROTOCOL)
        )
    # Datengebundene Layoutbausteine (Bindungen statt Fachkomponente)
    entries += [
        LibraryEntry("agenda_numbered", "data_protocol", "advanced", {"type": "list", "marker": "number", "source": "protocol.invitation_elements", "item": _t(_bind("item.title"))}, needs_protocol=True),
        LibraryEntry("open_tasks_table", "data_tasks", "advanced", {"type": "table", "source": "todos.open", "columns": [
            {"header": _t(_key("col.task")), "width": "fill", "cell": _t(_bind("item.task"))},
            {"header": _t(_key("col.assignee")), "cell": _t(_bind("item.assignee"))},
            {"header": _t(_key("col.due")), "cell": _t(_bind("item.due"))},
        ]}),
        LibraryEntry("participants_table", "data_people", "advanced", {"type": "table", "source": "protocol.participants", "columns": [
            {"header": _t(_key("col.name")), "width": "fill", "cell": _t(_bind("item.name"))},
            {"header": _t(_key("col.status")), "cell": _t(_bind("item.status"))},
        ]}, needs_protocol=True),
        LibraryEntry("upcoming_events_table", "data_events", "advanced", {"type": "table", "source": "events.upcoming", "limit": 10, "columns": [
            {"header": _t(_key("col.date")), "cell": _t(_bind("item.date"))},
            {"header": _t(_key("col.title")), "width": "fill", "cell": _t(_bind("item.title"))},
            {"header": _t(_key("col.location")), "cell": _t(_bind("item.location"))},
        ]}),
    ]
    return entries


LIBRARY: list[LibraryEntry] = [*_GENERAL, *_DOCUMENT, *_component_entries()]


def validate_library() -> None:
    """Jeder Eintrag ist ein gültiger Knoten (geprüft im Test und beim Import des Moduls)."""
    from pydantic import TypeAdapter

    from app.documents.layout import Node

    adapter = TypeAdapter(Node)
    for entry in LIBRARY:
        adapter.validate_python(entry.node)


def catalog_payload() -> dict[str, Any]:
    from app.documents import bindings
    from app.documents import catalog as data_catalog
    from app.documents.appearance import appearance_catalog
    from app.documents.doc_types import CATEGORIES, DOCUMENT_TYPES

    return {
        "node_types": {
            name: {
                "category": meta.category,
                "mode": meta.mode,
                "groups": list(meta.groups),
                "icon": meta.icon,
                "container": name in CONTAINER_TYPES,
                "master_only": name in MASTER_ONLY_TYPES,
            }
            for name, meta in NODE_TYPES.items()
        },
        "library": [
            {
                "key": entry.key,
                "group": entry.group,
                "mode": entry.mode,
                "node": entry.node,
                "master_only": entry.master_only,
                "access": entry.access,
                "needs_protocol": entry.needs_protocol,
            }
            for entry in LIBRARY
        ],
        "data_components": data_catalog.catalog_payload(),
        "appearance": appearance_catalog(),
        "bindings": bindings.catalog_payload(),
        "document_types": [{"key": item.key, "category": item.category, "needs_protocol": item.needs_protocol, "formats": list(item.formats)} for item in DOCUMENT_TYPES.values()],
        "categories": list(CATEGORIES),
        "modes": list(MODES),
    }
