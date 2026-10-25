"""Deterministische Test-Szenarien des Document Studio (Golden-, Renderer- und Compiler-Tests).

Ein Szenario ist eine Vorlage (TemplateContent-JSON, oft eine Systemvorlage), ein Brand-Profil
und feste Fachdaten je ``data_block``-Knoten. ``compile_scenario`` kompiliert ohne Datenbank:
Bindungen laufen im Beispielmodus (Texte aus documentPdf ``sample.*``), Fachkomponenten liefern
die Blöcke des Szenarios. Kein Datum «heute», keine Zufallswerte - die Goldens bleiben stabil.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Any

from app.core.locale_config_generated import SUPPORTED_LOCALES
from app.documents.appearance import APPEARANCE_BASES

UNICODE_SAMPLE = "Ħ ẞ Ç ø Ł Ж λ ✓ € £ 😀 👍🏽 🎉 🇨🇭 — „Zitat“ «Guillemets» #set $x$ *a* _b_ @ref <tag> `c` \\ [x] {y}"


def _p(text: str) -> dict:
    return {"t": "p", "c": [{"t": "text", "v": text}]}


def _table(columns: list[tuple[str, str, str]], rows: list[list[dict]], **extra) -> dict:
    return {
        "columns": [{"key": key, "label_key": label_key, "align": align} for key, label_key, align in columns],
        "groups": [{"rows": [{"cells": cells} for cells in rows]}] if rows else [],
        **extra,
    }


def _text(value: str) -> dict:
    return {"k": "text", "v": value}


def _amount(value: str) -> dict:
    return {"k": "amount", "v": value}


def _status(key: str) -> dict:
    return {"k": "status", "status": key}


def todo_table(count: int, *, prefix: str = "Aufgabe", title: str | None = "Pendenzen") -> dict:
    statuses = ["todoStatus.open", "todoStatus.in_progress", "todoStatus.done", "todoStatus.cancelled"]
    rows = [
        [
            _status(statuses[index % 4]),
            _text(f"{prefix} {index + 1:03d}"),
            _text(["Anna Muster", "Ben Beispiel", "Chloé Exemple", ""][index % 4]),
            _text(f"{(index % 28) + 1:02d}.{(index % 12) + 1:02d}.2026"),
        ]
        for index in range(count)
    ]
    return {
        "type": "todo_table",
        "title": title,
        "table": _table(
            [("status", "col.status", "left"), ("task", "col.task", "left"), ("assignee", "col.assignee", "left"), ("due", "col.due", "left")],
            rows,
        ),
    }


def protocol_elements(count: int, *, with_todos: bool = True, long_text: bool = False) -> list[dict]:
    paragraph = "Die Präsidentin begrüsst die Anwesenden und stellt die Beschlussfähigkeit fest. " * (6 if long_text else 1)
    elements = []
    for index in range(1, count + 1):
        children: list[dict] = [{"type": "richtext", "level": 2, "content": [_p(f"{index}. {paragraph}")]}]
        if index % 3 == 2:
            children.append({"type": "bullet_list", "level": 2, "items": ["Erstens", "Zweitens", "Drittens"]})
        if with_todos and index % 2 == 0:
            children.append({**todo_table(3, title=None), "title_key": "label.sessionTodos", "level": 2})
        elements.append({"type": "protocol_element", "title": f"Traktandum {index}", "responsible": "Anna Muster" if index % 2 else None, "children": children})
    return elements


def all_data_blocks() -> list[dict]:
    """Je ein Block jedes Fachkomponenten-Typs (Darstellung der Basis-Komponenten)."""
    return [
        {"type": "protocol_element", "title": "1. Begrüssung", "responsible": "Anna Muster", "children": [
            {"type": "richtext", "title": "Notizen", "level": 2, "content": [
                {"t": "h", "level": 2, "c": [{"t": "text", "v": "Zwischentitel"}]},
                {"t": "p", "c": [{"t": "text", "v": "Normal, "}, {"t": "text", "v": "fett", "b": True}, {"t": "text", "v": ", "}, {"t": "text", "v": "kursiv", "i": True}, {"t": "text", "v": ", "}, {"t": "text", "v": "code", "code": True}, {"t": "text", "v": ", "}, {"t": "text", "v": "Link", "href": "https://hocx.ch"}, {"t": "br"}, {"t": "text", "v": "nach hartem Umbruch"}]},
                {"t": "ul", "items": [[_p("Punkt eins")], [_p("Punkt zwei"), {"t": "ul", "items": [[_p("verschachtelt")]]}]]},
                {"t": "ol", "start": 3, "items": [[_p("drei")], [_p("vier")]]},
                {"t": "quote", "c": [_p("Ein Zitat")]},
                {"t": "code", "v": "#let x = 1\n$y$"},
            ]},
            {"type": "static_text", "level": 2, "content": [_p("Dieser Text kommt aus der Vorlage.")]},
            {"type": "session_date", "level": 2, "date": "14.11.2026"},
            {"type": "session_notes", "title": "Sitzungsnotizen", "level": 2, "content": [_p("Zeile eins"), _p("Zeile zwei")]},
            {"type": "form", "title": "Formular", "level": 2, "label_heading": "Feld", "value_heading": "Wert", "rows": [{"label": "Ort", "value": [_p("Vereinslokal")]}, {"label": "Leitung", "value": [_p("Ben Beispiel")]}]},
            {"type": "bullet_list", "title": "Aufzählung", "level": 2, "items": ["Erstens", "Zweitens"]},
        ]},
        {"type": "matrix", "title": "Matrix", "tables": [_table(
            [("label", "col.name", "left"), ("a", "col.value", "left"), ("b", "col.value", "left")],
            [[_text("Zeile A"), {"k": "rich", "rich": [_p("Zelle 1")]}, {"k": "rich", "rich": [{"t": "ul", "items": [[_p("x")], [_p("y")]]}]}],
             [_text("Zeile B"), _text("12.03.2026"), {"k": "rich", "rich": [{"t": "table", "header": ["K", "W"], "rows": [["a", "1"], ["b", "2"]]}]}]],
        )]},
        {"type": "entry_exit", "title": "Ein- und Austritte", "joins": [{"name": "Neu Mitglied", "date": "01.02.2026"}], "leaves": [{"name": "Alt Mitglied", "date": "31.01.2026"}]},
        {"type": "image", "title": "Bild", "image": {"path": "assets/fixture-1.png", "caption": "Bildunterschrift", "width_pt": 240}},
        {"type": "image_gallery", "title": "Galerie", "columns": 2, "images": [{"path": "assets/fixture-1.png", "caption": "Eins"}, {"path": "assets/fixture-2.png", "caption": "Zwei"}, {"path": "assets/missing.png", "caption": "Fehlt", "missing": True}]},
        {"type": "attendance", "title": "Anwesenheit", "entries": [{"name": "Anna Muster", "status": "present"}, {"name": "Ben Beispiel", "status": "late"}, {"name": "Chloé Exemple", "status": "excused"}, {"name": "Dario Esempio", "status": "absent"}, {"name": "Eva Ohne"}]},
        {"type": "attendance_matrix", "title": "Anwesenheitsmatrix", "sessions": ["05.01.", "12.01.", "19.01.", "26.01."], "people": ["Anna Muster", "Ben Beispiel"], "cells": [["present", "late", None, "absent"], ["excused", "present", "present", "present"]], "rates": ["50%", "75%"]},
        {"type": "member_list", "title": "Mitglieder", "table": _table([("name", "col.name", "left"), ("email", "col.email", "left"), ("phone", "col.phone", "left")], [[_text("Anna Muster"), _text("anna@example.ch"), _text("+41 79 000 00 00")]])},
        {"type": "signature_fields", "title": "Unterschriften", "fields": [{"label": "Präsidium", "name": "Anna Muster"}, {"label": "Protokoll", "name": "Ben Beispiel"}]},
        {"type": "attendance_sheet", "title": "Präsenzliste", "names": ["Anna Muster", "Ben Beispiel"], "columns": [], "blank_rows": 2},
        todo_table(6),
        {"type": "event_table", "title": "Termine", "table": {
            "columns": [{"key": "date", "label_key": "col.date"}, {"key": "title", "label_key": "col.title", "width": "fill"}, {"key": "tags", "label_key": "col.tags"}],
            "groups": [{"rows": [
                {"cells": [_text("05.01.2026"), _text("Generalversammlung"), {"k": "tags", "tags": [{"label": "GV", "color": "#2f6df6"}]}], "muted": True},
                {"cells": [_text("12.02.2026 – 14.02.2026"), _text("Skiweekend"), {"k": "tags", "tags": [{"label": "Anlass"}]}]},
            ]}],
        }},
        {"type": "event_calendar_month", "title": "Kalender", "months": [{"year": 2026, "month": 2, "first_weekday": 6, "days": 28, "events": {"12": [{"title": "Skiweekend", "color": "#12805c"}], "20": [{"title": "Hock", "muted": True}, {"title": "Abgesagt", "cancelled": True}]}}]},
        {"type": "event_agenda", "title": "Jahresprogramm", "months": [{"year": 2026, "month": 1, "items": [{"date": "05.01.", "title": "GV", "detail": "Vereinslokal", "tags": [{"label": "GV", "color": "#a855f7"}]}]}, {"year": 2026, "month": 3, "items": [{"date": "15.03.", "title": "Frühlingsputz", "cancelled": True}]}]},
        {"type": "list_table", "title": "Liste", "table": {"columns": [{"key": "one", "label": "Material"}, {"key": "two", "label": "Verantwortlich"}], "groups": [{"label": "Küche", "rows": [{"cells": [_text("Pfanne"), _text("Anna")]}]}, {"label_key": "group.noValue", "rows": [{"cells": [_text("Zelt"), {"k": "text", "v": "—", "tone": "warning"}]}]}]}},
        {"type": "finance_balance", "title": "Kontostand", "balances": [{"name": "Vereinskasse", "amount": "1'234.50", "currency": "CHF", "as_of": "31.12.2026"}, {"name": "Bussenkasse", "amount": "-12.00", "currency": "CHF", "negative": True}]},
        {"type": "finance_transactions", "title": "Buchungen", "table": {
            "columns": [{"key": "date", "label_key": "col.date"}, {"key": "description", "label_key": "col.description", "width": "fill"}, {"key": "amount", "label_key": "col.amount", "align": "right"}, {"key": "balance", "label_key": "col.balance", "align": "right"}],
            "groups": [{"label": "Januar 2026", "rows": [{"cells": [_text("05.01.2026"), _text("Mitgliederbeitrag"), _amount("+50.00 CHF"), _amount("50.00 CHF")]}], "subtotal": [{"k": "text", "v": "Zwischensumme"}, _text(""), _amount("+50.00 CHF"), _amount("")]}],
            "totals": [_text("Total"), _text(""), _amount("+50.00 CHF"), _amount("50.00 CHF")],
        }},
        {"type": "fines", "title": "Bussen", "table": _table([("person", "col.person", "left"), ("reason", "col.reason", "left"), ("amount", "col.amount", "right"), ("status", "col.status", "left")], [[_text("Ben Beispiel"), _text("Verspätet"), _amount("5.00 CHF"), _status("fineStatus.open")]], totals=[_text("Total"), _text(""), _amount("5.00 CHF"), _text("")])},
        {"type": "kpi_tiles", "title": "Kennzahlen", "tiles": [{"label_key": "kpi.sessions", "value": "24"}, {"label_key": "kpi.attendanceRate", "value": "87%", "tone": "success"}, {"label_key": "kpi.openTodos", "value": "7", "tone": "warning"}, {"label": "Eigene Zahl", "value": "1'234", "hint": "seit 2020"}]},
        {"type": "chart", "title": "Balken", "kind": "bar", "categories": ["Jan", "Feb", "Mär", "Apr"], "series": [{"label_key": "chart.income", "values": [100, 250, 80, 300], "tone": "success"}, {"label_key": "chart.expenses", "values": [50, 120, 160, 90], "tone": "danger"}], "value_format": "amount"},
        {"type": "chart", "title": "Gestapelt horizontal", "kind": "stacked_bar", "horizontal": True, "categories": ["Anna", "Ben", "Chloé"], "series": [{"label_key": "chart.present", "values": [10, 8, 5], "tone": "success"}, {"label_key": "chart.late", "values": [1, 2, 0], "tone": "info"}, {"label_key": "chart.absent", "values": [0, 1, 4], "tone": "danger"}]},
        {"type": "chart", "title": "Linie", "kind": "line", "categories": ["2022", "2023", "2024", "2025", "2026"], "series": [{"label_key": "chart.present", "values": [12, 15, 14, 18, 20]}]},
        {"type": "chart", "title": "Donut", "kind": "donut", "categories": ["Erledigt", "Offen"], "category_tones": ["success", "neutral"], "series": [{"values": [12, 5]}]},
        {"type": "stat_table", "title": "Statistiktabelle", "table": _table([("group", "col.group", "left"), ("sessions", "col.sessions", "right"), ("avg", "col.avgParticipants", "right")], [[_text("Jugend"), _amount("12"), _amount("8.5")]])},
    ]


def block(block_type: str, index: int = 0) -> dict:
    """Fixture-Block eines Typs (``index`` = n-tes Vorkommen, z. B. das zweite Diagramm)."""
    return [item for item in all_data_blocks() if item["type"] == block_type][index]


def fixture_assets() -> dict[str, bytes]:
    """Zwei kleine PNGs für Bild-Blöcke und eines als Logo (deterministisch)."""
    from PIL import Image, ImageDraw

    assets: dict[str, bytes] = {}
    for name, color in (("fixture-1", (47, 109, 246)), ("fixture-2", (18, 128, 92)), ("brand-logo", (168, 63, 47))):
        image = Image.new("RGB", (320, 120 if name == "brand-logo" else 200), color)
        draw = ImageDraw.Draw(image)
        draw.rectangle((12, 12, 308, 108 if name == "brand-logo" else 188), outline=(255, 255, 255), width=6)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        assets[f"assets/{name}.png"] = buffer.getvalue()
    return assets


# ── Szenarien ───────────────────────────────────────────────────────────────


@dataclass
class Scenario:
    content: dict[str, Any]
    blocks: dict[str, list[dict]] = field(default_factory=dict)
    document_type: str = "protocol"
    language: str = "de"
    brand: dict[str, Any] = field(default_factory=dict)
    is_draft: bool = False
    logo: bool = False
    pages: int = 1
    title: str = "Fixture-Dokument"


def system(key: str) -> dict[str, Any]:
    from app.documents.system_templates import SYSTEM_TEMPLATES

    definition = next(item for item in SYSTEM_TEMPLATES if item.key == key)
    return definition.build()


def _custom_header_content() -> dict[str, Any]:
    return {
        "page": {"size": "A4", "margins": {"top": 30, "right": 18, "bottom": 24, "left": 18}},
        "masters": [
            {
                "id": "default",
                "header": {"type": "header", "id": "h", "children": [
                    {"type": "container", "id": "h-box", "style": {"background": "$brand.primary", "padding": {"top": 2, "right": 3, "bottom": 2, "left": 3}}, "children": [
                        {"type": "row", "id": "h-row", "valign": "middle", "children": [
                            {"type": "image", "id": "h-logo", "source": {"kind": "binding", "path": "brand.logo"}, "style": {"width": "22mm", "height": "8mm"}},
                            {"type": "text", "id": "h-org", "role": "label", "content": {"default": [{"t": "bind", "path": "organization.name"}]}, "style": {"width": "fill", "text": {"color": "#FFFFFF"}}},
                            {"type": "text", "id": "h-date", "role": "small", "content": {"default": [{"t": "bind", "path": "document.date", "format": {"date": "long"}}]}, "style": {"text": {"color": "#FFFFFF"}}},
                        ]},
                    ]},
                ]},
                "footer": {"type": "footer", "id": "f", "children": [
                    {"type": "row", "id": "f-row", "children": [
                        {"type": "verify_note", "id": "f-verify", "show_qr": False, "style": {"width": "fill"}},
                        {"type": "page_number", "id": "f-page", "format": "page_of"},
                    ]},
                ]},
                "background": [{"type": "watermark", "id": "bg-wm", "when": "always", "text": {"default": [{"t": "text", "v": "INTERN"}]}, "size": 80}],
            },
            {"id": "first", "header": None, "footer": {"type": "footer", "id": "first-f", "children": [{"type": "text", "id": "first-f-text", "role": "small", "content": {"default": [{"t": "bind", "path": "organization.address"}]}, "style": {"text": {"align": "center"}}}]}},
        ],
        "settings": {"first_page_master": "first", "auto_verify_note": False},
        "body": [
            {"type": "text", "id": "title", "role": "title", "content": {"default": [{"t": "bind", "path": "document.title"}]}},
            {"type": "data_block", "id": "protocol", "component": "protocol_element"},
        ],
    }


def _multi_column_content() -> dict[str, Any]:
    return {
        "page": {"size": "A4", "columns": 2, "column_gap": 8},
        "masters": [system("protocol_compact")["masters"][0]],
        "body": [
            {"type": "text", "id": "title", "role": "title", "content": {"default": [{"t": "bind", "path": "document.title"}]}},
            {"type": "row", "id": "facts", "gap": 4, "children": [
                {"type": "container", "id": "fact-1", "style": {"width": "1fr", "background": "$brand.surface", "padding": {"top": 2, "right": 2, "bottom": 2, "left": 2}}, "children": [{"type": "text", "id": "fact-1-t", "role": "label", "content": {"default": [{"t": "key", "key": "kpi.sessions"}]}}]},
                {"type": "container", "id": "fact-2", "style": {"width": "1fr", "background": "$brand.surface", "padding": {"top": 2, "right": 2, "bottom": 2, "left": 2}}, "children": [{"type": "text", "id": "fact-2-t", "role": "label", "content": {"default": [{"t": "key", "key": "kpi.members"}]}}]},
            ]},
            {"type": "data_block", "id": "protocol", "component": "protocol_element"},
        ],
    }


def _cover_content() -> dict[str, Any]:
    return {
        "masters": [system("protocol_standard")["masters"][0]],
        "title_page": {
            "enabled": True,
            "background": "$brand.primary",
            "children": [
                {"type": "absolute_layer", "id": "cover", "anchor": "page", "children": [
                    {"type": "image", "id": "cover-logo", "source": {"kind": "binding", "path": "brand.logo"}, "style": {"width": "50mm"}, "frame": {"x": 20, "y": 20, "width": 50}},
                    {"type": "text", "id": "cover-title", "role": "title", "content": {"default": [{"t": "bind", "path": "document.title"}]}, "style": {"text": {"color": "#FFFFFF", "size": 34}}, "frame": {"x": 20, "y": 120, "width": 170}},
                    {"type": "text", "id": "cover-date", "role": "subtitle", "content": {"default": [{"t": "bind", "path": "document.date", "format": {"date": "long"}}]}, "style": {"text": {"color": "#FFFFFF"}}, "frame": {"x": 20, "y": 150, "width": 170}},
                    {"type": "divider", "id": "cover-line", "color": "#FFFFFF", "thickness": 2, "length": "60mm", "frame": {"x": 20, "y": 165, "width": 60}},
                ]},
            ],
        },
        "body": [{"type": "toc", "id": "toc"}, {"type": "page_break", "id": "pb"}, {"type": "data_block", "id": "protocol", "component": "protocol_element"}],
    }


def _conditions_content() -> dict[str, Any]:
    return {
        "masters": [system("protocol_compact")["masters"][0]],
        "body": [
            {"type": "text", "id": "shown", "content": {"default": [{"t": "text", "v": "SICHTBAR-OFFENE-AUFGABEN"}]}, "visible_if": {"op": "count", "path": "protocol.open_todos", "cmp": "gt", "value": 0}},
            {"type": "text", "id": "hidden", "content": {"default": [{"t": "text", "v": "VERSTECKT-KEINE-AUFGABEN"}]}, "visible_if": {"op": "count", "path": "protocol.open_todos", "cmp": "eq", "value": 0}},
            {"type": "text", "id": "brand-off", "content": {"default": [{"t": "text", "v": "VERSTECKT-BRAND"}]}, "visible_if": {"op": "eq", "path": "brand.toc", "value": True}},
            {"type": "text", "id": "disabled", "enabled": False, "content": {"default": [{"t": "text", "v": "VERSTECKT-DEAKTIVIERT"}]}},
            {"type": "stack", "id": "repeat", "repeat": {"source": "protocol.participants"}, "children": [
                {"type": "text", "id": "repeat-name", "content": {"default": [{"t": "text", "v": "PERSON: "}, {"t": "bind", "path": "item.name"}]}},
            ]},
            {"type": "table", "id": "todos", "source": "protocol.open_todos", "columns": [
                {"id": "c1", "header": {"default": [{"t": "key", "key": "col.task"}]}, "width": "fill", "cell": {"default": [{"t": "bind", "path": "item.task"}]}},
                {"id": "c2", "header": {"default": [{"t": "key", "key": "col.due"}]}, "cell": {"default": [{"t": "bind", "path": "item.due", "format": {"date": "weekday"}}]}},
            ]},
        ],
    }


def _page_size_content(size: str, orientation: str) -> dict[str, Any]:
    content = system("protocol_compact")
    content["page"] = {"size": size, "orientation": orientation, "margins": {"top": 15, "right": 14, "bottom": 15, "left": 14}}
    return content


def all_blocks_content() -> dict[str, Any]:
    return {"masters": [system("protocol_compact")["masters"][0]], "body": [{"type": "data_block", "id": "all", "component": "protocol_element"}]}


def _override_sample(title: str) -> dict:
    return {"type": "protocol_element", "title": title, "children": [
        {"type": "session_date", "level": 2, "date": "14.11.2026, 19:30"},
        {"type": "attendance", "title": "Anwesenheit", "level": 2, "entries": [{"name": "Anna Muster", "status": "present"}, {"name": "Ben Beispiel", "status": "excused"}]},
        {**todo_table(3, title="Pendenzen"), "level": 2},
    ]}


def scenarios() -> dict[str, Scenario]:
    items = {
        "protocol_simple": Scenario(system("protocol_standard"), {"protocol": protocol_elements(3)}, is_draft=True),
        "protocol_multipage": Scenario(system("protocol_formal"), {"protocol": [*protocol_elements(8, long_text=True), {"type": "protocol_element", "title": "Pendenzen", "children": [{**todo_table(60, title=None), "level": 2}]}]}, logo=True, pages=4),
        "protocol_tables_images": Scenario(system("protocol_standard"), {"protocol": [{"type": "protocol_element", "title": "Inhalte", "children": [block("matrix"), block("image"), block("image_gallery"), block("todo_table")]}]}, pages=2),
        "attendance_list": Scenario(system("attendance_list"), {"attendance": [block("attendance")]}, document_type="attendance"),
        "finance_report": Scenario(system("finance_report"), {"balances": [block("finance_balance")], "monthly": [block("stat_table")], "chart": [block("chart")]}, document_type="finance"),
        "statistics_report": Scenario(system("statistics_report"), {"kpis": [block("kpi_tiles")], "attendance-chart": [block("chart", 2)], "attendance-table": [block("stat_table")], "groups": [block("stat_table")]}, document_type="statistics"),
        "multi_column": Scenario(_multi_column_content(), {"protocol": protocol_elements(6, long_text=True)}, pages=2),
        "title_page": Scenario(_cover_content(), {"protocol": protocol_elements(2)}, logo=True, pages=3),
        "custom_header": Scenario(_custom_header_content(), {"protocol": protocol_elements(6, long_text=True)}, logo=True, pages=2),
        "conditions": Scenario(_conditions_content()),
        "long_table": Scenario(system("todos_standard"), {"todos": [todo_table(500)]}, document_type="todos", pages=2),
        "fonts": Scenario(system("protocol_compact"), {"protocol": protocol_elements(2)}, brand={"typography": {"body": {"builtin": "liberation_serif"}, "heading": {"builtin": "noto_sans"}, "base_size": 11.5}, "layout": {"heading_style": "boxed", "table_style": "grid"}}),
        "page_a5": Scenario(_page_size_content("A5", "portrait"), {"protocol": protocol_elements(2)}, pages=2),
        "page_letter_landscape": Scenario(_page_size_content("Letter", "landscape"), {"protocol": protocol_elements(2)}),
        "all_blocks": Scenario(all_blocks_content(), {"all": all_data_blocks()}, document_type="custom", pages=6),
        "unicode": Scenario({"masters": [system("protocol_compact")["masters"][0]], "body": [
            {"type": "text", "id": "u-title", "role": "title", "content": {"default": [{"t": "text", "v": UNICODE_SAMPLE}]}},
            {"type": "list", "id": "u-list", "items": [UNICODE_SAMPLE, "漢字 かな 한국어"]},
            {"type": "data_block", "id": "u-todos", "component": "todo_table"},
        ]}, {"u-todos": [todo_table(2, prefix=UNICODE_SAMPLE)]}, document_type="custom"),
    }
    # Grundstile (Brand Studio) auf allen Fachkomponenten; «classic» ist all_blocks
    for base, definition in APPEARANCE_BASES.items():
        if base != "classic":
            items[f"appearance_{base}"] = Scenario(all_blocks_content(), {"all": all_data_blocks()}, document_type="custom", pages=6, brand={"appearance": {"base": base}, "layout": dict(definition["layout"])})
    # Block-Übersteuerung im Designer: ein Block weicht vom Grundstil des Profils ab
    items["appearance_block_override"] = Scenario(
        {"masters": [system("protocol_compact")["masters"][0]], "body": [
            {"type": "data_block", "id": "plain", "component": "protocol_element"},
            {"type": "data_block", "id": "styled", "component": "protocol_element", "appearance": {"attendance": {"variant": "table"}, "session_date": {"variant": "box", "corners": "rounded"}, "table": {"variant": "zebra"}}},
        ]},
        {"plain": [_override_sample("Grundstil")], "styled": [_override_sample("Übersteuert")]},
        document_type="custom",
    )
    for language in sorted(SUPPORTED_LOCALES):
        if language != "de":
            items[f"lang_{language}"] = Scenario(system("protocol_standard"), {"protocol": protocol_elements(2)}, language=language)
    for name, flags in VERIFY_VARIANTS.items():
        items[name] = Scenario(system("protocol_compact"), {"protocol": protocol_elements(1, with_todos=False)}, brand={"verify": dict(zip(("show_url", "show_id", "show_qr"), flags))})
    return items


# Echtheitsprüfung im Dokument: (Prüf-URL, Kurz-ID, QR-Code)
VERIFY_VARIANTS = {"verify-all": (True, True, True), "verify-qr": (False, False, True), "verify-url-id": (True, True, False), "verify-none": (False, False, False)}


def compile_scenario(scenario: Scenario, *, render_id: str = "0192f0aa-0000-7000-8000-000000000001") -> Any:
    """Kompiliert ein Szenario ohne Datenbank. Rückgabe: CompiledDocument."""
    from app.documents.brand import BrandTokens
    from app.documents.brand_service import resolve_brand
    from app.documents.compiler import CompileInput, LayoutCompiler, _mark_empty
    from app.documents.context import BuildContext
    from app.documents.layout import TemplateContent
    from app.documents.model import BLOCK_MODELS, DocumentMeta, RenderInfo
    from app.documents.strings import strings_for

    class _NoDb:
        def get(self, *args, **kwargs):
            return None

        def scalars(self, *args, **kwargs):
            return []

        def query(self, *args, **kwargs):  # pragma: no cover - Szenarien nutzen keine Komponentenverweise
            raise AssertionError("Szenario braucht keine Datenbank")

    class ScenarioCompiler(LayoutCompiler):
        def _node_data_block(self, node, scope, area, scope_def):
            fixture = scenario.blocks.get(node.id)
            if fixture is None:
                return super()._node_data_block(node, scope, area, scope_def)
            blocks = _mark_empty([BLOCK_MODELS[item["type"]].model_validate(item) for item in fixture])
            return self._data_output(node, blocks)

    db = _NoDb()
    tokens = BrandTokens.model_validate(scenario.brand)
    brand = resolve_brand(db, 1, None, tokens=tokens)
    assets = fixture_assets()
    if scenario.logo:
        brand.files["assets/brand-logo.png"] = assets["assets/brand-logo.png"]
        brand.env["logo"] = "assets/brand-logo.png"
        brand.env["header_show_logo"] = tokens.layout.header_footer.header_show_logo
    strings = strings_for(scenario.language)
    meta = DocumentMeta(document_type=scenario.document_type, title=scenario.title, number="P-2026-07", date="13.10.2026", status="held", version="v0.3", tenant_name="Testverein", language=scenario.language)
    render = RenderInfo(document_id=render_id, short_id="0000-0001", verify_display="abgabe.example.ch/verify", verify_link=f"https://abgabe.example.ch/verify?id={render_id}")
    ctx = BuildContext(db=db, tenant_id=1, language=scenario.language)
    document_env = {"title": scenario.title, "subtitle": None, "type": strings.get(f"docType.{scenario.document_type}", ""), "date": "2026-10-13", "number": "P-2026-07", "version": "v0.3", "status": strings.get("protocolStatus.held", ""), "language": scenario.language, "is_draft": scenario.is_draft, "short_id": "0000-0001"}
    data = CompileInput(
        content=TemplateContent.model_validate(scenario.content),
        brand=brand,
        ctx=ctx,
        meta=meta,
        strings=strings,
        render=render,
        mode="sample",
        strict=False,
        is_draft=scenario.is_draft,
        document_env=document_env,
    )
    compiled = ScenarioCompiler(data, db).compile()
    compiled.files.update({path: content for path, content in assets.items() if path.startswith("assets/fixture-")})
    return compiled
