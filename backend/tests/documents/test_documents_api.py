"""Routen Export Center: Export (PDF), Vorschau (inkl. Studio-Vorschau und Rechte), Zusatzformate,
Exporthistorie, Auswahlquellen, Mandantentrennung."""
from __future__ import annotations

import asyncio
from datetime import date

import pytest

from tests.render_helpers import render_now
from fastapi import HTTPException

from app.api.routes import documents as routes
from app.documents.service import DocumentRequest
from app.models import DocumentTemplate
from tests.factories import (
    make_app_user,
    make_current_user,
    make_event,
    make_protocol,
    make_protocol_element,
    make_protocol_element_block,
    make_protocol_text,
    make_protocol_todo,
    make_template,
    make_tenant,
)


@pytest.fixture(autouse=True)
def _keep_test_transaction(db, monkeypatch):
    """Routen rollen bei kuratierten Fehlern zurück. In der Testsitzung würde das die ganze
    Testwelt verwerfen; die äussere Testtransaktion räumt ohnehin auf."""
    monkeypatch.setattr(db, "rollback", lambda: None)


@pytest.fixture
def setup(db):
    tenant = make_tenant(db, "API-Verein")
    other = make_tenant(db, "Anderer Verein")
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, protocol_number="A-1", protocol_date=date(2026, 6, 1))
    element = make_protocol_element(db, protocol.id, section_name="Traktandum 1")
    text_block = make_protocol_element_block(db, element.id, {}, element_type_code="text")
    make_protocol_text(db, text_block.id, "Inhalt")
    todo_block = make_protocol_element_block(db, element.id, {}, element_type_code="todo", sort_index=1)
    make_protocol_todo(db, todo_block.id, task="Getränke besorgen", tenant_id=tenant.id)
    make_event(db, tenant.id, title="Sommerfest", event_date=date(2099, 7, 4))
    users = {role: make_app_user(db, email=f"{role}@api.example", tenant_id=tenant.id, role_code=role) for role in ("reader", "writer", "admin")}
    return {
        "tenant": tenant,
        "other": other,
        "protocol": protocol,
        "reader": make_current_user(tenant.id, role="reader", user_id=users["reader"].id),
        "writer": make_current_user(tenant.id, role="writer", user_id=users["writer"].id),
        "admin": make_current_user(tenant.id, role="admin", user_id=users["admin"].id),
        "other_admin": make_current_user(other.id, role="admin", user_id=users["admin"].id),
    }


def test_render_protocol_and_list_exports(db, setup):
    body = DocumentRequest(protocol_id=setup["protocol"].public_id)
    result = render_now(body, db=db, user=setup["reader"])
    assert result.document_type == "protocol" and result.content_url
    assert result.verify_url.endswith(f"/verify?id={result.id}") and len(result.short_id) == 9
    assert result.template_system_key == "protocol_standard" and result.design_hash and result.content_hash
    listed = routes.list_document_exports(protocol_id=setup["protocol"].public_id, document_type=None, limit=5, offset=0, db=db, user=setup["admin"])
    assert [item.id for item in listed] == [result.id]


def test_foreign_protocol_and_template_are_not_found(db, setup):
    with pytest.raises(HTTPException) as excinfo:
        render_now(DocumentRequest(protocol_id=setup["protocol"].public_id), db=db, user=setup["other_admin"])
    assert excinfo.value.status_code == 404
    own = DocumentTemplate(tenant_id=setup["tenant"].id, origin="tenant", name="Eigen", document_type="todos")
    db.add(own)
    db.flush()
    with pytest.raises(HTTPException) as excinfo:
        render_now(DocumentRequest(document_type="todos", template_id=own.public_id), db=db, user=setup["other_admin"])
    assert excinfo.value.status_code == 404


def test_studio_preview_fields_are_rejected_on_export(db, setup):
    with pytest.raises(HTTPException) as excinfo:
        render_now(DocumentRequest(document_type="todos", data_mode="sample"), db=db, user=setup["admin"])
    assert excinfo.value.status_code == 422


def test_preview_returns_png_data_urls_and_diagnostics(db, setup):
    result = asyncio.run(routes.preview_document(DocumentRequest(protocol_id=setup["protocol"].public_id), _ConnectedRequest(), max_pages=1, db=db, user=setup["reader"]))
    assert result.pages and result.pages[0].startswith("data:image/png;base64,")
    assert result.template_source == "platform_default" and result.diagnostics == []


def test_preview_of_unsaved_content_needs_edit_rights(db, setup):
    content = {"masters": [{"id": "default"}], "body": [{"type": "text", "id": "t", "content": {"default": [{"t": "bind", "path": "gibt.es_nicht"}]}}]}
    body = DocumentRequest(document_type="custom", content=content, data_mode="sample")
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(routes.preview_document(body, _ConnectedRequest(), max_pages=1, db=db, user=setup["reader"]))
    assert excinfo.value.status_code == 403
    result = asyncio.run(routes.preview_document(body, _ConnectedRequest(), max_pages=1, db=db, user=setup["writer"]))
    assert [(item.node_id, item.code) for item in result.diagnostics] == [("t", "unknownBinding")]
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(routes.preview_document(DocumentRequest(document_type="custom", brand_tokens={}), _ConnectedRequest(), max_pages=1, db=db, user=setup["writer"]))
    assert excinfo.value.status_code == 403


def test_extra_formats(db, setup):
    csv = routes.export_document_format(routes.FormatExportRequest(document_type="todos", format="csv"), db=db, user=setup["reader"])
    assert "Getränke besorgen" in csv.body.decode("utf-8")
    markdown = routes.export_document_format(routes.FormatExportRequest(document_type="todos", format="markdown"), db=db, user=setup["reader"])
    assert "Getränke besorgen" in markdown.body.decode("utf-8")
    ics = routes.export_document_format(routes.FormatExportRequest(document_type="events", format="ics"), db=db, user=setup["reader"])
    assert "BEGIN:VCALENDAR" in ics.body.decode("utf-8") and "Sommerfest" in ics.body.decode("utf-8")
    xlsx = routes.export_document_format(routes.FormatExportRequest(protocol_id=setup["protocol"].public_id, format="xlsx"), db=db, user=setup["reader"])
    assert xlsx.body[:2] == b"PK"
    with pytest.raises(HTTPException) as excinfo:
        routes.export_document_format(routes.FormatExportRequest(document_type="form", format="csv"), db=db, user=setup["reader"])
    assert excinfo.value.status_code == 422


def test_page_params_reach_matching_components(db, setup):
    # Filter der Todo-Seite: nur erledigte - keine Zeile, also keine Tabelle für CSV
    with pytest.raises(HTTPException) as excinfo:
        routes.export_document_format(routes.FormatExportRequest(document_type="todos", format="csv", params={"status": "done"}), db=db, user=setup["reader"])
    assert excinfo.value.status_code == 422
    csv = routes.export_document_format(routes.FormatExportRequest(document_type="todos", format="csv", params={"status": "all"}), db=db, user=setup["reader"])
    assert "Getränke besorgen" in csv.body.decode("utf-8")


def test_sources_are_tenant_scoped(db, setup):
    options = routes.list_source_options("protocols", protocol_id=None, db=db, user=setup["admin"])
    assert [option.label for option in options] == ["A-1"]
    assert routes.list_source_options("protocols", protocol_id=None, db=db, user=setup["other_admin"]) == []
    with pytest.raises(HTTPException):
        routes.list_source_options("gibts_nicht", protocol_id=None, db=db, user=setup["admin"])


def test_readers_cannot_export_protocol_drafts_without_watermark(db, setup):
    """STUDIO-007: «Wasserzeichen aus» bei Protokollentwürfen nur mit Schreibrecht."""
    from app.documents import service
    from app.documents.service import ExportOptions

    request = DocumentRequest(protocol_id=setup["protocol"].public_id, options=ExportOptions(watermark="off"))
    as_reader = service.prepare(db, setup["reader"], setup["tenant"].id, request)
    as_writer = service.prepare(db, setup["writer"], setup["tenant"].id, request)
    assert as_reader.compiled.data["flags"]["draft"] is True
    assert as_writer.compiled.data["flags"]["draft"] is False


def test_overridden_protocol_title_is_noted_in_the_registry(db, setup):
    from sqlalchemy import select

    from app.documents.service import ExportOptions
    from app.models import DocumentRegistry

    plain = render_now(DocumentRequest(protocol_id=setup["protocol"].public_id), db=db, user=setup["writer"])
    renamed = render_now(
        DocumentRequest(protocol_id=setup["protocol"].public_id, options=ExportOptions(title="Genehmigtes Protokoll")), db=db, user=setup["writer"],
    )
    flags = dict(db.execute(select(DocumentRegistry.public_id, DocumentRegistry.title_overridden)).all())
    assert flags[plain.id] is False and flags[renamed.id] is True


def test_list_sources_and_list_export_require_writer(db, setup):
    """TYPST-002: Leser bekommen weder die Listenauswahl noch den Listeninhalt (wie GET /api/lists)."""
    with pytest.raises(HTTPException) as excinfo:
        routes.list_source_options("lists", protocol_id=None, db=db, user=setup["reader"])
    assert excinfo.value.status_code == 403
    with pytest.raises(HTTPException) as excinfo:
        render_now(DocumentRequest(document_type="list"), db=db, user=setup["reader"])
    assert excinfo.value.status_code == 403
    assert routes.list_source_options("lists", protocol_id=None, db=db, user=setup["writer"]) == []


def test_reader_can_download_own_rendered_pdf(db, setup):
    """TYPST-003: Leser dürfen ihre selbst erzeugten PDFs ohne Protokollbezug laden, andere
    Leser und fremde Mandanten nicht; Schreibende wie bisher."""
    from app.api.routes import files as file_routes
    from app.models import StoredFile
    from app.services.access_service import AccessService

    tenant = setup["tenant"]
    owner = make_app_user(db, "leser-pdf@example.com", tenant_id=tenant.id, role_code="reader")
    other = make_app_user(db, "anderer-leser@example.com", tenant_id=tenant.id, role_code="reader")
    reader = make_current_user(tenant.id, role="reader", user_id=owner.id)
    result = render_now(DocumentRequest(document_type="statistics"), db=db, user=reader)
    assert result.content_url
    response = file_routes.get_stored_file_content(result.generated_file_id, db=db, user=reader)
    assert response.status_code == 200

    stored = db.query(StoredFile).filter(StoredFile.public_id == result.generated_file_id).one()
    access = AccessService()
    with pytest.raises(HTTPException) as excinfo:
        access.ensure_can_read_stored_file(db, make_current_user(tenant.id, role="reader", user_id=other.id), stored.id)
    assert excinfo.value.status_code == 403
    with pytest.raises(HTTPException) as excinfo:
        access.ensure_can_read_stored_file(db, make_current_user(setup["other"].id, role="reader", user_id=owner.id), stored.id)
    assert excinfo.value.status_code == 403
    access.ensure_can_read_stored_file(db, make_current_user(tenant.id, role="writer", user_id=other.id), stored.id)


class _ConnectedRequest:
    """Stand-in für den Request der Vorschau-Route: der Client bleibt verbunden."""

    async def is_disconnected(self) -> bool:
        return False
