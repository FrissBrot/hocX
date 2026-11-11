"""PDF-Integritäts-Audit: was im Editor steht, kommt im PDF an - oder der Editor markiert es.

Läuft in der CI bei jeder Änderung an Editor oder PDF (.github/workflows/pdf-integrity.yml) und in
der normalen Backend-Suite. Drei Ebenen:

1. Markdown des Editors → Dokumentmodell: jede Textzeile des Editor-Korpus
   (fixtures/editor_richtext_corpus.json, erzeugt vom echten Serializer des Editors in
   frontend/components/ui/rich-text-markdown.test.ts) bleibt vollständig erhalten.
2. Protokoll → echtes PDF über den Export-Pfad (service.render, Typst, Objektspeicher): jede
   Zeile jedes exportierten Blocks steht im Text des PDFs.
3. Abdeckung (export_coverage.py): was nicht exportiert wird, erscheint nicht im PDF und ist
   genau dann gemeldet - das ist die Markierung «Nicht im PDF» im Editor.
4. Nichts zu viel: im Editor weggefilterte Termine (Tag, Zeitraum, Anzahl) und entfernte
   Inhalte stehen nicht im PDF; Aufgaben im PDF sind genau die des Editors. Dass Editor und PDF
   Termine gleich filtern, prüft zusätzlich der gemeinsame Katalog
   (tests/test_event_filter_parity.py und frontend event-filter-parity.test.ts).
"""
from __future__ import annotations

import asyncio
import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select

from app.core.storage import MAIN, get_object_store
from app.documents import service
from app.documents.context import BuildContext
from app.documents.export_coverage import protocol_pdf_coverage
from app.documents.richtext import markdown_to_rich
from app.documents.service import DocumentRequest
from app.models import ProtocolElementBlock, ProtocolImage, StoredFile
from tests.documents.conftest import normalize, pdf_text
from tests.factories import (
    make_protocol,
    make_protocol_element,
    make_protocol_element_block,
    make_protocol_text,
    make_event,
    make_protocol_todo,
    make_template,
    make_tenant,
)

CORPUS = json.loads((Path(__file__).parent / "fixtures" / "editor_richtext_corpus.json").read_text(encoding="utf-8"))


def _texts(value: Any) -> list[str]:
    """Alle Textwerte (``v``) eines Dokumentmodells in Lesereihenfolge."""
    if isinstance(value, dict):
        out = [value["v"]] if isinstance(value.get("v"), str) else []
        for key, item in value.items():
            if key != "v":
                out.extend(_texts(item))
        return out
    if isinstance(value, list):
        return [text for item in value for text in _texts(item)]
    return []


def _missing(lines: list[str], haystack: str) -> list[str]:
    """Zeilen, die im Text fehlen. Steht eine Zeile nicht am Stück da, müssen wenigstens alle
    ihre Wörter vorkommen: pdftotext stellt Zeichen aus Ersatzschriften (Emoji) teils vor das
    vorangehende Wort, der Inhalt ist trotzdem im PDF."""
    target = normalize(haystack)
    return [line for line in lines if normalize(line) not in target and any(normalize(word) not in target for word in line.split())]


def test_corpus_covers_every_editor_case():
    assert len(CORPUS) >= 10, "Editor-Korpus fehlt oder ist leer (UPDATE_RICHTEXT_CORPUS=1 im Frontend)"
    assert all(case["lines"] for case in CORPUS)


@pytest.mark.parametrize("case", CORPUS, ids=[case["name"] for case in CORPUS])
def test_editor_markdown_keeps_every_line_in_the_model(case):
    rich = [node.model_dump(mode="json") for node in markdown_to_rich(case["markdown"])]
    assert _missing(case["lines"], "".join(_texts(rich))) == []


def _image(db, tenant_id: int, block_id: int, *, scan_status: str) -> None:
    stored = StoredFile(
        tenant_id=tenant_id,
        original_name="foto.jpg",
        mime_type="image/jpeg",
        storage_path=f"tests/pdf-integrity/{block_id}.jpg",
        file_size_bytes=1,
        checksum_sha256="0" * 64,
        scan_status=scan_status,
    )
    db.add(stored)
    db.flush()
    db.add(ProtocolImage(protocol_element_block_id=block_id, stored_file_id=stored.id, caption="Foto im Scan"))
    db.flush()


def _protocol(db):
    """Protokoll mit allen Korpusfällen und den gängigen Blocktypen. Gibt (tenant, protocol,
    erwartete Zeilen je Block, nicht exportierte Inhalte, erwartete Abdeckung) zurück."""
    tenant = make_tenant(db, "Integritätsverein")
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, protocol_number="INT-1", protocol_date=date(2026, 11, 10), status="durchgeführt")
    expected: dict[str, list[str]] = {}

    texts = make_protocol_element(db, protocol.id, sort_index=0, section_name="Texte aus dem Editor")
    for index, case in enumerate(CORPUS):
        block = make_protocol_element_block(db, texts.id, {}, sort_index=index, element_type_code="text")
        make_protocol_text(db, block.id, case["markdown"])
        expected[str(block.public_id)] = case["lines"]

    data = make_protocol_element(db, protocol.id, sort_index=1, section_name="Weitere Bausteine")
    todo = make_protocol_element_block(db, data.id, {}, sort_index=0, element_type_code="todo")
    for index, task in enumerate(["Protokoll versenden an alle", "Halle reservieren <bis Freitag>", "Budget & Offerte $ prüfen"]):
        make_protocol_todo(db, todo.id, task=task, sort_index=index)
    expected[str(todo.public_id)] = ["Protokoll versenden an alle", "Halle reservieren <bis Freitag>", "Budget & Offerte $ prüfen"]
    bullets = make_protocol_element_block(db, data.id, {"bullet_items": ["Erster Listenpunkt", "Zweiter # Listenpunkt", "Dritter @ Listenpunkt"]}, sort_index=1, element_type_code="bullet_list")
    expected[str(bullets.public_id)] = ["Erster Listenpunkt", "Zweiter # Listenpunkt", "Dritter @ Listenpunkt"]
    form = make_protocol_element_block(
        db, data.id,
        {"rows": [{"label": "Ort der Sitzung", "value_type": "text", "text_value": "Pfadiheim Waldegg"}, {"label": "Leitung", "value_type": "text", "text_value": "Anna *Muster*"}]},
        sort_index=2, element_type_code="form",
    )
    expected[str(form.public_id)] = ["Ort der Sitzung", "Pfadiheim Waldegg", "Leitung", "Anna *Muster*"]

    # Terminliste mit Filter: Tag «Lager», nur künftige, höchstens zwei. Alles andere ist im
    # Editor weggefiltert und darf nicht im PDF stehen.
    for title, day, tag in [
        ("Lageraufbau Juniwoche", date(2026, 11, 20), "Lager"),
        ("Lagerabbau Dezemberwoche", date(2026, 12, 5), "Lager"),
        ("Lagerextra Überzählig", date(2026, 12, 20), "Lager"),
        ("Lagerrückblick Vergangen", date(2026, 10, 1), "Lager"),
        ("Grillplausch Fremdtag", date(2026, 11, 25), "Hock"),
    ]:
        make_event(db, tenant.id, title=title, event_date=day).tag = tag
    events = make_protocol_element_block(
        db, data.id, {"event_filter": {"tags": ["Lager"], "range": {"mode": "future"}, "limit": 2}},
        sort_index=6, element_type_code="event_list",
    )
    expected[str(events.public_id)] = ["Lageraufbau Juniwoche", "Lagerabbau Dezemberwoche"]

    # Nicht exportiert: Block mit Inhalt (ausgeschaltet), leerer ausgeschalteter Block,
    # ganzes Traktandum ausgeschaltet, Sitzungsnotizen, Bild im Virenscan.
    hidden_block = make_protocol_element_block(db, data.id, {}, sort_index=3, element_type_code="text")
    hidden_block.export_visible_snapshot = False
    make_protocol_text(db, hidden_block.id, "Interne Notiz Blockgeheim")
    empty_hidden = make_protocol_element_block(db, data.id, {}, sort_index=4, element_type_code="text")
    empty_hidden.export_visible_snapshot = False
    image_block = make_protocol_element_block(db, data.id, {}, sort_index=5, element_type_code="image")
    _image(db, tenant.id, image_block.id, scan_status="pending")

    hidden_element = make_protocol_element(db, protocol.id, sort_index=2, section_name="Vorstandsinternes")
    hidden_element.export_visible_snapshot = False
    internal = make_protocol_element_block(db, hidden_element.id, {}, sort_index=0, element_type_code="text")
    make_protocol_text(db, internal.id, "Traktandum Elementgeheim")
    notes = make_protocol_element(db, protocol.id, sort_index=3, section_name="Sitzungsnotizen")
    notes_block = make_protocol_element_block(db, notes.id, {}, sort_index=0, element_type_code="text")
    make_protocol_text(db, notes_block.id, "Notizen Notizgeheim")
    db.flush()

    secrets = ["Blockgeheim", "Elementgeheim", "Notizgeheim", "Lagerextra Überzählig", "Lagerrückblick Vergangen", "Grillplausch Fremdtag"]
    coverage = {
        "elements": {str(hidden_element.public_id): "element_not_exported", str(notes.public_id): "session_notes"},
        "blocks": {str(hidden_block.public_id): "block_not_exported", str(image_block.public_id): "image_unavailable"},
    }
    return tenant, protocol, expected, secrets, coverage


def _coverage_map(coverage) -> dict[str, dict[str, str]]:
    data = coverage.as_dict()
    return {"elements": {e["id"]: e["reason"] for e in data["elements"]}, "blocks": {b["id"]: b["reason"] for b in data["blocks"]}}


def test_every_editor_line_reaches_the_exported_pdf(db):
    tenant, protocol, expected, secrets, expected_coverage = _protocol(db)

    coverage = protocol_pdf_coverage(db, None, tenant.id, protocol)
    assert coverage.layout_checked, "Protokoll-Vorlage nicht auflösbar: Abdeckung ohne Vorlagenprüfung"
    assert _coverage_map(coverage) == expected_coverage

    result = asyncio.run(service.render(db, None, tenant.id, DocumentRequest(protocol_id=protocol.public_id, document_type="protocol")))
    text = pdf_text(get_object_store().get_bytes(MAIN, result.stored_file.storage_path))

    reported = set(expected_coverage["blocks"])
    missing = {block_id: _missing(lines, text) for block_id, lines in expected.items() if block_id not in reported}
    assert {block_id: lines for block_id, lines in missing.items() if lines} == {}, "Inhalt aus dem Editor fehlt im PDF"
    leaked = [secret for secret in secrets if normalize(secret) in normalize(text)]
    assert leaked == [], "Nicht exportierter Inhalt steht im PDF"


def test_layout_that_drops_blocks_is_reported(db):
    """Eine Protokoll-Vorlage, die nur Text setzt (Inhaltsfilter), lässt Todos weg: die
    Abdeckung meldet das, statt dass die Todos still im PDF fehlen."""
    tenant = make_tenant(db, "Filterverein")
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, protocol_number="INT-2")
    element = make_protocol_element(db, protocol.id, section_name="Traktandum")
    text = make_protocol_element_block(db, element.id, {}, sort_index=0, element_type_code="text")
    make_protocol_text(db, text.id, "Bleibt im PDF")
    todo = make_protocol_element_block(db, element.id, {}, sort_index=1, element_type_code="todo")
    make_protocol_todo(db, todo.id, task="Fällt durch den Filter")
    db.flush()
    layout = {"masters": [{"id": "default"}], "body": [
        {"type": "data_block", "id": "elements", "component": "protocol_element", "params": {"content": "text"}},
    ]}

    coverage = protocol_pdf_coverage(db, None, tenant.id, protocol, layout_content=layout)

    assert _coverage_map(coverage) == {"elements": {}, "blocks": {str(todo.public_id): "omitted_by_layout"}}


@pytest.mark.parametrize("status", ["durchgeführt", "abgeschlossen"])
def test_pdf_todos_are_exactly_the_editor_todos(db, status):
    """Aufgaben im PDF = Aufgaben, die der Editor zeigt (gleiche Route wie die Protokollseite),
    in jedem Status - auch erledigte und abgebrochene, und nach dem Abschluss aus dem
    eingefrorenen Stand."""
    from app.api.routes import todos as todos_route
    from app.documents.providers.protocol import map_block
    from app.models import TodoStatus
    from tests.factories import make_current_user

    tenant = make_tenant(db, f"Aufgabenverein {status}")
    protocol = make_protocol(db, tenant.id, make_template(db, tenant.id).id, protocol_number="INT-3", status="durchgeführt")
    element = make_protocol_element(db, protocol.id)
    block = make_protocol_element_block(db, element.id, {}, element_type_code="todo")
    status_ids = {code: status_id for code, status_id in db.execute(select(TodoStatus.code, TodoStatus.id))}
    for index, code in enumerate(["open", "in_progress", "done", "cancelled"]):
        make_protocol_todo(db, block.id, task=f"Aufgabe {code}", sort_index=index).todo_status_id = status_ids[code]
    db.flush()
    user = make_current_user(tenant.id, role="admin")
    if status == "abgeschlossen":
        # Momentaufnahme wie beim Abschluss; eine spätere Aufgabe gehört weder in Editor noch PDF
        live = [todo.model_dump(mode="json") for todo in todos_route.list_todos(block.public_id, db=db, user=user)]
        protocol.status = "abgeschlossen"
        protocol.todos_snapshot_json = {"blocks": {str(block.id): live}, "pending": []}
        db.flush()
        make_protocol_todo(db, block.id, task="Aufgabe nach Abschluss", sort_index=9)

    editor = [todo.task for todo in todos_route.list_protocol_block_todos(protocol.public_id, db=db, user=user)[block.public_id]]
    ctx = BuildContext(db=db, tenant_id=tenant.id, language="de", protocol=protocol)
    pdf = [cell.v for group in map_block(ctx, protocol, block).table.groups for row in group.rows for cell in row.cells if cell.v.startswith("Aufgabe ")]
    assert pdf == editor == ["Aufgabe open", "Aufgabe in_progress", "Aufgabe done", "Aufgabe cancelled"]


def test_coverage_changes_nothing(db):
    tenant, protocol, *_ = _protocol(db)
    count = select(func.count()).select_from(ProtocolElementBlock)
    before = db.scalar(count)
    protocol_pdf_coverage(db, None, tenant.id, protocol)
    after = db.scalar(count)
    assert before == after
