"""Galerie: jeder Hausstil × jeder Dokumenttyp rendert mit Beispieldaten.

Mit ``DOCUMENT_GALLERY_OUT=/pfad/galerie.pdf`` werden alle PDFs zu einer Galerie
zusammengeführt (CI lädt sie als Artefakt hoch, optional für die Docs-Site).
"""
from __future__ import annotations

import asyncio
import io
import os
from datetime import date, timedelta
from pathlib import Path

import pytest

from app.documents import service
from app.documents.doc_types import DOCUMENT_TYPE_KEYS
from app.documents.service import DocumentRequest, StyleOverride
from app.documents.style_tokens import STYLE_KEYS, default_tokens
from app.models import FinanceTransaction
from tests.factories import (
    make_event,
    make_finance_account,
    make_fine,
    make_list_definition,
    make_list_entry,
    make_participant,
    make_protocol,
    make_protocol_element,
    make_protocol_element_block,
    make_protocol_text,
    make_protocol_todo,
    make_template,
    make_template_participant,
    make_tenant,
)

GALLERY_OUT = os.environ.get("DOCUMENT_GALLERY_OUT")


@pytest.fixture
def sample(db):
    today = date.today()
    tenant = make_tenant(db, "Musterverein")
    template = make_template(db, tenant.id, name="Vorstandssitzung")
    people = [make_participant(db, tenant.id, name) for name in ("Anna Muster", "Ben Beispiel", "Chloé Exemple", "Dario Esempio")]
    for person in people:
        make_template_participant(db, template.id, person.id)
        person.joined_at = date(today.year, 2, 1)
    protocol = make_protocol(db, tenant.id, template.id, protocol_number="VS-12", protocol_date=today, status="durchgeführt")
    protocol.title = "Vorstandssitzung März"
    element = make_protocol_element(db, protocol.id, section_name="Begrüssung")
    text = make_protocol_element_block(db, element.id, {}, element_type_code="text")
    make_protocol_text(db, text.id, "Die Präsidentin begrüsst die Anwesenden und eröffnet die **Sitzung**.")
    make_protocol_element_block(
        db, element.id,
        {"attendance_entries": [{"participant_id": person.id, "participant_name": person.display_name, "status": status} for person, status in zip(people, ("present", "late", "excused", "absent"))]},
        element_type_code="attendance", sort_index=1,
    )
    todo_block = make_protocol_element_block(db, element.id, {}, element_type_code="todo", sort_index=2)
    for index, task in enumerate(("Saal reservieren", "Einladung verschicken", "Kasse prüfen")):
        make_protocol_todo(db, todo_block.id, task=task, sort_index=index, tenant_id=tenant.id)
    for offset, title in ((7, "Hock"), (30, "Sommerfest"), (90, "Herbstwanderung")):
        make_event(db, tenant.id, title=title, event_date=today + timedelta(days=offset))
    account = make_finance_account(db, tenant.id, name="Vereinskasse")
    for offset, amount, description in ((-40, 500, "Mitgliederbeiträge"), (-20, -120.5, "Material"), (-5, 80, "Spende")):
        db.add(FinanceTransaction(account_id=account.id, amount=amount, description=description, transaction_date=today + timedelta(days=offset)))
    make_fine(db, protocol.id, account.id, amount=5, participant_name_snapshot="Ben Beispiel")
    material = make_list_definition(db, tenant.id, name="Material", column_one_title="Gegenstand", column_two_title="Verantwortlich")
    for index, (item, owner) in enumerate((("Zelt", "Anna"), ("Grill", "Ben"), ("Lautsprecher", ""))):
        make_list_entry(db, material.id, sort_index=index, column_one_value={"text_value": item}, column_two_value={"text_value": owner})
    db.flush()
    return {"tenant": tenant, "protocol": protocol, "list": material}


def test_every_style_renders_every_document_type(db, sample):
    pdfs: list[tuple[str, bytes]] = []
    for style_key in STYLE_KEYS:
        for document_type in DOCUMENT_TYPE_KEYS:
            request = DocumentRequest(
                document_type=document_type,
                protocol_id=sample["protocol"].public_id,
                params={"list_id": str(sample["list"].public_id)} if document_type == "list" else {},
                style_override=StyleOverride(style_key=style_key, tokens=default_tokens(style_key)),
            )
            result = asyncio.run(service.render(db, None, sample["tenant"].id, request))
            from app.core.config import settings

            pdf = (Path(settings.storage_root) / result.stored_file.storage_path).read_bytes()
            assert pdf.startswith(b"%PDF"), (style_key, document_type)
            pdfs.append((f"{style_key} · {document_type}", pdf))
    if GALLERY_OUT:
        from pypdf import PdfReader, PdfWriter

        writer = PdfWriter()
        for label, pdf in pdfs:
            start = len(writer.pages)
            for page in PdfReader(io.BytesIO(pdf)).pages:
                writer.add_page(page)
            writer.add_outline_item(label, start)
        with open(GALLERY_OUT, "wb") as handle:
            writer.write(handle)
