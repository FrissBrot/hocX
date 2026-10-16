"""Erzeugt die Dokument-Fixtures (JSON) für die Renderer-, Matrix- und Golden-Tests.

    python -m tests.documents.fixtures.generate     (im Backend-Container, Arbeitsverzeichnis backend/)

Die erzeugten Dateien werden eingecheckt; die Tests lesen nur die JSON-Dateien. Inhalte sind
bewusst deterministisch (keine Zufallswerte, kein Datum «heute»), damit Goldens stabil bleiben.
Bilder referenzieren assets/fixture-*.png, die die Tests aus ``fixture_assets()`` erzeugen.
"""
from __future__ import annotations

import io
import json
from pathlib import Path


from app.core.locale_config_generated import SUPPORTED_LOCALES
from app.documents.model import Document
from app.documents.strings import strings_for

FIXTURE_DIR = Path(__file__).resolve().parent

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


def todo_table(count: int, *, prefix: str = "Aufgabe") -> dict:
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
        "title": "Pendenzen",
        "table": _table(
            [("status", "col.status", "left"), ("task", "col.task", "left"), ("assignee", "col.assignee", "left"), ("due", "col.due", "left")],
            rows,
        ),
    }


def all_blocks() -> list[dict]:
    return [
        {"type": "heading", "text": "Überschrift erster Stufe"},
        {"type": "richtext", "title": "Rich Text", "content": [
            {"t": "h", "level": 2, "c": [{"t": "text", "v": "Zwischentitel"}]},
            {"t": "p", "c": [{"t": "text", "v": "Normal, "}, {"t": "text", "v": "fett", "b": True}, {"t": "text", "v": ", "}, {"t": "text", "v": "kursiv", "i": True}, {"t": "text", "v": ", "}, {"t": "text", "v": "durchgestrichen", "s": True}, {"t": "text", "v": ", "}, {"t": "text", "v": "code", "code": True}, {"t": "text", "v": ", "}, {"t": "text", "v": "Link", "href": "https://hocx.ch"}, {"t": "br"}, {"t": "text", "v": "nach hartem Umbruch"}]},
            {"t": "ul", "items": [[_p("Punkt eins")], [_p("Punkt zwei"), {"t": "ul", "items": [[_p("verschachtelt")]]}]]},
            {"t": "ol", "start": 3, "items": [[_p("drei")], [_p("vier")]]},
            {"t": "quote", "c": [_p("Ein Zitat")]},
            {"t": "code", "v": "#let x = 1\n$y$"},
        ]},
        {"type": "static_text", "title": "Fester Text", "content": [_p("Dieser Text kommt aus der Vorlage.")]},
        {"type": "spacer", "size": "s"},
        {"type": "divider"},
        {"type": "toc", "title": "Inhalt", "depth": 2},
        {"type": "protocol_element", "title": "1. Begrüssung", "responsible": "Anna Muster", "children": [
            {"type": "richtext", "title": "Notizen", "level": 2, "content": [_p("Die Präsidentin begrüsst die Anwesenden.")]},
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
        {"type": "qr_link", "title": "QR-Code", "url": "https://hocx.ch/protocols/123", "label": "Protokoll online"},
        {"type": "generic_table", "title": "Tabelle", "table": _table([("a", "col.name", "left"), ("b", "col.value", "right")], [[_text("Eins"), _amount("1")], [{"k": "check", "checked": True}, {"k": "blank"}]])},
        {"type": "page_break"},
        {"type": "heading", "text": "Nach dem Seitenumbruch", "level": 2},
    ]


def document(name: str, blocks: list[dict], *, language: str = "de", orientation: str = "portrait", title_page: str = "modern", toc: str = "on", watermark: bool = True) -> dict:
    doc = {
        "meta": {
            "document_type": "custom",
            "title": f"Fixture {name}",
            "subtitle": "Dokument-Engine",
            "number": "P-2026-07",
            "date": "13.10.2026",
            "status": "held",
            "version": "v0.3",
            "tenant_name": "Testverein",
            "language": language,
        },
        "options": {"title_page": title_page, "toc": toc, "toc_block_titles": True, "numbering": True, "orientation": orientation, "watermark": watermark},
        "style": {"key": "modern", "sender": "Testverein\nPostfach 1\n8000 Zürich", "place": "Zürich"},
        "strings": strings_for(language),
        "render": {
            "document_id": "0192f0aa-0000-7000-8000-000000000001",
            "short_id": "0000-0001",
            "verify_display": "abgabe.example.ch/verify",
            "verify_link": "https://abgabe.example.ch/verify?id=0192f0aa-0000-7000-8000-000000000001",
        },
        "blocks": blocks,
    }
    # Über das Modell normalisieren: die Fixture enthält alle Standardwerte wie im Betrieb.
    return Document.model_validate(doc).model_dump(mode="json")


def fixture_assets() -> dict[str, bytes]:
    """Zwei kleine PNGs für die Bild-Blöcke (deterministisch)."""
    from PIL import Image, ImageDraw

    assets: dict[str, bytes] = {}
    for index, color in ((1, (47, 109, 246)), (2, (18, 128, 92))):
        image = Image.new("RGB", (320, 200), color)
        draw = ImageDraw.Draw(image)
        draw.rectangle((20, 20, 300, 180), outline=(255, 255, 255), width=6)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        assets[f"assets/fixture-{index}.png"] = buffer.getvalue()
    return assets


def build() -> dict[str, dict]:
    fixtures = {
        "short": document("kurz", [todo_table(3), {"type": "richtext", "title": "Notiz", "content": [_p("Kurzer Text.")]}], title_page="none", toc="off"),
        "long": document("lang", [todo_table(500)], title_page="none", toc="off", watermark=False),
        "unicode": document("Unicode 😀", [
            {"type": "richtext", "title": UNICODE_SAMPLE, "content": [_p(UNICODE_SAMPLE)]},
            {"type": "bullet_list", "items": [UNICODE_SAMPLE, "漢字 かな 한국어"]},
            todo_table(2, prefix=UNICODE_SAMPLE),
        ]),
        "all_blocks": document("alle Blöcke", all_blocks()),
        "empty": document("leer", [{"type": block_type, "hide_if_empty": False, "empty": True, **extra} for block_type, extra in (
            ("richtext", {}), ("todo_table", {"table": {"columns": [{"key": "a"}]}}), ("event_table", {"table": {"columns": [{"key": "a"}]}}),
            ("attendance", {}), ("chart", {}), ("image_gallery", {}), ("finance_balance", {}),
        )], title_page="none"),
        "landscape": document("quer", all_blocks(), orientation="landscape", title_page="cover"),
    }
    for language in sorted(SUPPORTED_LOCALES):
        fixtures[f"lang_{language}"] = document(f"Sprache {language}", [todo_table(4), {"type": "attendance", "entries": [{"name": "A", "status": "present"}, {"name": "B", "status": "absent"}]}], language=language, title_page="minimal")
    return fixtures


def main() -> None:
    for name, payload in build().items():
        path = FIXTURE_DIR / f"{name}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"geschrieben: {path.name}")


if __name__ == "__main__":
    main()
