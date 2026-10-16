"""Routen der Dokument-Engine: Rendern, Vorschau, Zusatzformate, Hausstile, Assets, Rezepte."""
from __future__ import annotations

import asyncio
import io
from datetime import date

import pytest
from fastapi import HTTPException
from starlette.datastructures import Headers, UploadFile

from app.api.routes import documents as routes
from app.documents.catalog import BlockSpec
from app.documents.service import DocumentRequest
from app.documents.style_tokens import DocumentStyleTokens
from tests.factories import (
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
    make_event(db, tenant.id, title="Sommerfest", event_date=date(2026, 7, 4))
    admin = make_current_user(tenant.id, role="admin")
    return {"tenant": tenant, "other": other, "protocol": protocol, "admin": admin, "other_admin": make_current_user(other.id, role="admin")}


def test_render_protocol_and_list_exports(db, setup):
    body = DocumentRequest(protocol_id=setup["protocol"].public_id)
    result = asyncio.run(routes.render_document(body, db=db, user=setup["admin"]))
    assert result.document_type == "protocol" and result.content_url
    assert result.verify_url.endswith(f"/verify?id={result.id}") and len(result.short_id) == 9
    listed = routes.list_document_exports(protocol_id=setup["protocol"].public_id, limit=5, db=db, user=setup["admin"])
    assert [item.id for item in listed] == [result.id]


def test_foreign_protocol_is_not_found(db, setup):
    body = DocumentRequest(protocol_id=setup["protocol"].public_id)
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(routes.render_document(body, db=db, user=setup["other_admin"]))
    assert excinfo.value.status_code == 404


def test_preview_returns_png_data_urls(db, setup):
    body = DocumentRequest(document_type="todos")
    result = asyncio.run(routes.preview_document(body, _ConnectedRequest(), max_pages=2, db=db, user=setup["admin"]))
    assert result.pages and result.pages[0].startswith("data:image/png;base64,")


def test_extra_formats(db, setup):
    user = setup["admin"]
    csv = routes.export_document_format(routes.FormatExportRequest(document_type="todos", params={"status": "all"}, format="csv"), db=db, user=user)
    assert "Getränke besorgen" in csv.body.decode("utf-8")
    xlsx = routes.export_document_format(routes.FormatExportRequest(document_type="todos", format="xlsx"), db=db, user=user)
    assert xlsx.body[:2] == b"PK"
    markdown = routes.export_document_format(routes.FormatExportRequest(document_type="todos", format="markdown"), db=db, user=user)
    assert "Getränke besorgen" in markdown.body.decode("utf-8")
    ics = routes.export_document_format(
        routes.FormatExportRequest(blocks=[BlockSpec(type="event_table", params={"date_from": "2026-01-01"})], format="ics"), db=db, user=user
    )
    assert "SUMMARY:Sommerfest" in ics.body.decode("utf-8")
    with pytest.raises(HTTPException) as excinfo:
        routes.export_document_format(routes.FormatExportRequest(document_type="members", format="ics"), db=db, user=user)
    assert excinfo.value.status_code == 422


def test_invalid_block_is_422(db, setup):
    body = DocumentRequest(blocks=[BlockSpec(type="todo_table", params={"status": "kaputt"})])
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(routes.preview_document(body, _ConnectedRequest(), max_pages=1, db=db, user=setup["admin"]))
    assert excinfo.value.status_code == 422


def test_catalog_lists_all_block_types(setup):
    catalog = routes.get_catalog(user=setup["admin"])
    assert len(catalog["blocks"]) == 34
    assert {item["key"] for item in catalog["document_types"]} >= {"protocol", "todos", "events", "statistics"}


def test_style_crud_and_isolation(db, setup):
    admin = setup["admin"]
    created = routes.create_document_style(routes.DocumentStyleWrite(name="Klassisch", style_key="classic", tokens=DocumentStyleTokens(primary_color="#112233")), db=db, user=admin)
    assert created.style_key == "classic" and created.is_default  # erster Stil wird Standard
    updated = routes.update_document_style(created.id, routes.DocumentStyleWrite(tokens=DocumentStyleTokens(primary_color="#445566")), db=db, user=admin)
    assert updated.version == 2
    with pytest.raises(HTTPException) as excinfo:
        routes.update_document_style(created.id, routes.DocumentStyleWrite(name="x"), db=db, user=setup["other_admin"])
    assert excinfo.value.status_code == 404
    with pytest.raises(HTTPException) as excinfo:
        routes.delete_document_style(created.id, db=db, user=admin)
    assert excinfo.value.status_code == 409  # letzter Stil
    reader = make_current_user(setup["tenant"].id, role="reader")
    with pytest.raises(HTTPException):
        routes.create_document_style(routes.DocumentStyleWrite(name="x"), db=db, user=reader)


def test_asset_upload_validation(db, setup, monkeypatch):
    from app import scanner
    from PIL import Image

    async def clean(contents, **_kwargs):
        return ["clean" for _ in contents]

    monkeypatch.setattr(scanner, "scan_many", clean)
    # Template-Code ist kein gültiger Upload
    bad = UploadFile(io.BytesIO(b"#let x = 1"), filename="evil.typ")
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(routes.upload_document_style_asset(kind="font", file=bad, db=db, user=setup["admin"]))
    assert excinfo.value.status_code == 422
    buffer = io.BytesIO()
    Image.new("RGB", (40, 20), (10, 20, 30)).save(buffer, format="PNG")
    upload = UploadFile(io.BytesIO(buffer.getvalue()), filename="logo.png", headers=Headers({"content-type": "image/png"}))
    asset = asyncio.run(routes.upload_document_style_asset(kind="image", file=upload, db=db, user=setup["admin"]))
    assert asset.kind == "image" and asset.mime_type == "image/png"
    style = routes.create_document_style(routes.DocumentStyleWrite(name="Mit Logo", tokens=DocumentStyleTokens(logo_asset_id=asset.id, header="logo")), db=db, user=setup["admin"])
    with pytest.raises(HTTPException) as excinfo:
        routes.delete_document_style_asset(asset.id, db=db, user=setup["admin"])
    assert excinfo.value.status_code == 409  # noch verwendet
    with pytest.raises(HTTPException):
        routes.create_document_style(routes.DocumentStyleWrite(name="Fremd", tokens=DocumentStyleTokens(logo_asset_id=asset.id)), db=db, user=setup["other_admin"])
    preview = asyncio.run(routes.preview_document(DocumentRequest(document_type="todos", style_id=style.id), _ConnectedRequest(), max_pages=1, db=db, user=setup["admin"]))
    assert preview.pages


def test_recipe_crud(db, setup):
    writer = make_current_user(setup["tenant"].id, role="writer")
    recipe = routes.create_document_recipe(
        routes.DocumentRecipeWrite(name="Monatsbrief", document_type="custom", blocks=[BlockSpec(type="heading", params={"text": "Hallo"}), BlockSpec(type="event_agenda")]),
        db=db,
        user=writer,
    )
    assert [block.type for block in recipe.blocks] == ["heading", "event_agenda"]
    with pytest.raises(HTTPException) as excinfo:
        routes.update_document_recipe(recipe.id, routes.DocumentRecipeWrite(blocks=[BlockSpec(type="heading", params={"farbe": "rot"})]), db=db, user=writer)
    assert excinfo.value.status_code == 422
    preview = asyncio.run(routes.preview_document(DocumentRequest(recipe_id=recipe.id), _ConnectedRequest(), max_pages=1, db=db, user=writer))
    assert preview.pages
    routes.delete_document_recipe(recipe.id, db=db, user=writer)
    assert routes.list_document_recipes(db=db, user=writer) == []


def test_sources_are_tenant_scoped(db, setup):
    protocols = routes.list_source_options("protocols", protocol_id=None, db=db, user=setup["admin"])
    assert [item.id for item in protocols] == [setup["protocol"].public_id]
    assert routes.list_source_options("protocols", protocol_id=None, db=db, user=setup["other_admin"]) == []
    elements = routes.list_source_options("protocol_elements", protocol_id=setup["protocol"].public_id, db=db, user=setup["admin"])
    assert [item.label for item in elements] == ["Traktandum 1"]
    assert routes.list_source_options("protocol_blocks", protocol_id=setup["protocol"].public_id, db=db, user=setup["other_admin"]) == []
    with pytest.raises(HTTPException):
        routes.list_source_options("geheim", protocol_id=None, db=db, user=setup["admin"])


def test_list_sources_and_list_export_require_writer(db, setup):
    """TYPST-002: Leser bekommen weder die Listenauswahl noch den Listeninhalt (wie GET /api/lists)."""
    reader = make_current_user(setup["tenant"].id, role="reader")
    with pytest.raises(HTTPException) as excinfo:
        routes.list_source_options("lists", protocol_id=None, db=db, user=reader)
    assert excinfo.value.status_code == 403
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(routes.render_document(DocumentRequest(document_type="list"), db=db, user=reader))
    assert excinfo.value.status_code == 403
    writer = make_current_user(setup["tenant"].id, role="writer")
    assert routes.list_source_options("lists", protocol_id=None, db=db, user=writer) == []


def test_reader_can_download_own_rendered_pdf(db, setup):
    """TYPST-003: Leser dürfen ihre selbst erzeugten PDFs ohne Protokollbezug laden, andere
    Leser und fremde Mandanten nicht; Schreibende wie bisher."""
    from app.api.routes import files as file_routes
    from app.models import StoredFile
    from app.services.access_service import AccessService
    from tests.factories import make_app_user

    tenant = setup["tenant"]
    owner = make_app_user(db, "leser-pdf@example.com", tenant_id=tenant.id, role_code="reader")
    other = make_app_user(db, "anderer-leser@example.com", tenant_id=tenant.id, role_code="reader")
    reader = make_current_user(tenant.id, role="reader", user_id=owner.id)
    result = asyncio.run(routes.render_document(DocumentRequest(document_type="statistics"), db=db, user=reader))
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

