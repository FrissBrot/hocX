"""Routen Document Studio: Vorlagen-Lebenszyklus (Entwurf, Autosave mit Konflikterkennung,
Veröffentlichung, Unveränderlichkeit, Vergleich, Wiederherstellung, Archiv), Systemvorlagen,
Zuweisungen und Prioritätsregel, Brand-Profile, Assets, Komponenten, Rechte, Mandantentrennung."""
from __future__ import annotations

import asyncio
import io
from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from starlette.datastructures import Headers, UploadFile

from app.api.routes import document_studio as studio
from app.api.routes import documents as routes
from app.documents import template_service
from app.documents.service import DocumentRequest
from app.models import DocumentTemplate, DocumentTemplateRevision
from tests.factories import make_app_user, make_current_user, make_protocol, make_template, make_tenant

SIMPLE = {"masters": [{"id": "default"}], "body": [{"type": "text", "id": "t", "content": {"default": [{"t": "text", "v": "Erster Stand"}]}}]}


@pytest.fixture(autouse=True)
def _keep_test_transaction(db, monkeypatch):
    monkeypatch.setattr(db, "rollback", lambda: None)


@pytest.fixture
def world(db):
    tenant = make_tenant(db, "Studio-Verein")
    other = make_tenant(db, "Fremder Verein")
    users = {role: make_app_user(db, email=f"{role}@studio.example", tenant_id=tenant.id, role_code=role) for role in ("reader", "writer", "admin")}
    foreign = make_app_user(db, email="admin@fremd.example", tenant_id=other.id, role_code="admin")
    protocol_template = make_template(db, tenant.id, name="Vorstand")
    protocol = make_protocol(db, tenant.id, protocol_template.id, protocol_number="S-1", protocol_date=date(2026, 6, 1))
    return {
        "tenant": tenant,
        "protocol_template": protocol_template,
        "protocol": protocol,
        "reader": make_current_user(tenant.id, role="reader", user_id=users["reader"].id),
        "writer": make_current_user(tenant.id, role="writer", user_id=users["writer"].id),
        "admin": make_current_user(tenant.id, role="admin", user_id=users["admin"].id),
        "foreign": make_current_user(other.id, role="admin", user_id=foreign.id),
    }


def _create(db, world, **extra):
    body = studio.TemplateCreate(name="Mein Protokoll", document_type="protocol", content=SIMPLE, **extra)
    return studio.create_document_template(body, db=db, user=world["writer"])


def test_template_lifecycle(db, world):
    created = _create(db, world)
    assert created.origin == "tenant" and created.draft_revision.revision_no == 1 and created.published_revision is None
    assert created.editable and not created.is_default

    lock = created.draft_revision.lock_version
    changed = {**SIMPLE, "body": [{"type": "text", "id": "t", "content": {"default": [{"t": "text", "v": "Zweiter Stand"}]}}]}
    saved = studio.save_document_template_draft(created.id, studio.DraftSave(content=changed, lock_version=lock), db=db, user=world["writer"])
    assert saved.revision.lock_version == lock + 1 and saved.diagnostics == []
    with pytest.raises(HTTPException) as excinfo:
        studio.save_document_template_draft(created.id, studio.DraftSave(content=SIMPLE, lock_version=lock), db=db, user=world["writer"])
    assert excinfo.value.status_code == 409 and excinfo.value.detail["lock_version"] == lock + 1

    with pytest.raises(HTTPException) as excinfo:
        studio.publish_document_template(created.id, studio.PublishBody(), db=db, user=world["writer"])
    assert excinfo.value.status_code == 403
    published = studio.publish_document_template(created.id, studio.PublishBody(note="v1"), db=db, user=world["admin"])
    assert published.published_revision.revision_no == 1 and published.draft_revision is None

    # Veröffentlichte Revision ist unveränderlich (DB-Trigger)
    revision = db.scalar(select(DocumentTemplateRevision).where(DocumentTemplateRevision.public_id == published.published_revision.id))
    savepoint = db.begin_nested()
    with pytest.raises(DBAPIError):
        db.execute(text("UPDATE document_template_revision SET content_json = '{}'::jsonb WHERE id = :id"), {"id": revision.id})
    savepoint.rollback()

    # Neuer Entwurf, zweite Veröffentlichung, Vergleich und Wiederherstellung
    studio.save_document_template_draft(created.id, studio.DraftSave(content=SIMPLE), db=db, user=world["writer"])
    second = studio.publish_document_template(created.id, studio.PublishBody(), db=db, user=world["admin"])
    revisions = studio.list_document_template_revisions(created.id, db=db, user=world["reader"])
    assert [(item.revision_no, item.status) for item in revisions] == [(2, "published"), (1, "superseded")]
    diff = studio.compare_document_template_revisions(created.id, from_revision=revisions[1].id, to_revision=revisions[0].id, db=db, user=world["reader"])
    assert diff["nodes"] == [{"change": "modified", "node_id": "t", "type": "text", "name": None, "area": "body", "fields": ["content"]}]
    restored = studio.restore_document_template_revision(created.id, revisions[1].id, db=db, user=world["writer"])
    assert restored.draft_revision.revision_no == 3 and restored.content["body"][0]["content"]["default"][0]["v"] == "Zweiter Stand"
    discarded = studio.discard_document_template_draft(created.id, db=db, user=world["writer"])
    assert discarded.draft_revision is None and second.published_revision.revision_no == 2


def test_readers_only_see_the_published_revision(db, world):
    """STUDIO-018: Leser sehen weder Inhalt noch Revision eines Entwurfs."""
    created = _create(db, world)
    published = studio.publish_document_template(created.id, studio.PublishBody(), db=db, user=world["admin"])
    changed = {**SIMPLE, "body": [{"type": "text", "id": "t", "content": {"default": [{"t": "text", "v": "Geheimer Entwurf"}]}}]}
    draft = studio.save_document_template_draft(created.id, studio.DraftSave(content=changed), db=db, user=world["writer"]).revision

    as_reader = studio.get_document_template(created.id, db=db, user=world["reader"])
    assert as_reader.working_revision_id == published.published_revision.id
    assert as_reader.content["body"][0]["content"]["default"][0]["v"] == "Erster Stand"
    assert [item.status for item in studio.list_document_template_revisions(created.id, db=db, user=world["reader"])] == ["published"]
    with pytest.raises(HTTPException) as excinfo:
        studio.get_document_template_revision(created.id, draft.id, db=db, user=world["reader"])
    assert excinfo.value.status_code == 404
    with pytest.raises(HTTPException) as excinfo:
        studio.compare_document_template_revisions(created.id, from_revision=published.published_revision.id, to_revision=draft.id, db=db, user=world["reader"])
    assert excinfo.value.status_code == 404

    as_writer = studio.get_document_template(created.id, db=db, user=world["writer"])
    assert as_writer.working_revision_id == draft.id and as_writer.content["body"][0]["content"]["default"][0]["v"] == "Geheimer Entwurf"
    assert studio.get_document_template_revision(created.id, draft.id, db=db, user=world["writer"])["revision"]["status"] == "draft"


def test_invalid_layout_is_never_saved(db, world):
    created = _create(db, world)
    with pytest.raises(HTTPException) as excinfo:
        studio.save_document_template_draft(created.id, studio.DraftSave(content={"masters": [{"id": "default"}], "body": [{"type": "text", "id": "a"}, {"type": "text", "id": "a"}]}), db=db, user=world["writer"])
    assert excinfo.value.status_code == 422 and excinfo.value.detail["code"] == "duplicateId"
    with pytest.raises(HTTPException) as excinfo:
        studio.save_document_template_draft(created.id, studio.DraftSave(content={"body": [{"type": "script", "id": "x"}]}), db=db, user=world["writer"])
    assert excinfo.value.status_code == 422 and excinfo.value.detail["code"] == "schema"


def test_publish_is_blocked_by_errors(db, world):
    broken = {"masters": [{"id": "default"}], "body": [{"type": "data_block", "id": "x", "component": "todo_table", "params": {"status": "kaputt"}}]}
    created = studio.create_document_template(studio.TemplateCreate(name="Kaputt", document_type="todos", content=broken), db=db, user=world["writer"])
    assert [item["code"] for item in created.diagnostics] == ["invalidParams"]
    with pytest.raises(HTTPException) as excinfo:
        studio.publish_document_template(created.id, studio.PublishBody(), db=db, user=world["admin"])
    assert excinfo.value.status_code == 422 and excinfo.value.detail["diagnostics"][0]["node_id"] == "x"


def test_system_templates_are_read_only_and_copyable(db, world):
    system = db.query(DocumentTemplate).filter(DocumentTemplate.system_key == "protocol_formal").one()
    listed = {item.system_key: item for item in studio.list_document_templates(document_type="protocol", include_archived=False, db=db, user=world["reader"])}
    assert set(listed) >= {"protocol_standard", "protocol_formal", "protocol_compact", "protocol_short", "protocol_decisions"}
    assert listed["protocol_standard"].is_default and not listed["protocol_formal"].editable
    with pytest.raises(HTTPException) as excinfo:
        studio.save_document_template_draft(system.public_id, studio.DraftSave(content=SIMPLE), db=db, user=world["admin"])
    assert excinfo.value.status_code == 403
    copy = studio.duplicate_document_template(system.public_id, studio.DuplicateBody(name="Unser Protokoll"), db=db, user=world["writer"])
    assert copy.origin == "copy" and copy.source_system_key == "protocol_formal" and copy.editable
    assert copy.content == template_service.revision_content(template_service.published_revision(db, system)).model_dump(mode="json")


def test_tenant_isolation(db, world):
    created = _create(db, world)
    with pytest.raises(HTTPException) as excinfo:
        studio.get_document_template(created.id, db=db, user=world["foreign"])
    assert excinfo.value.status_code == 404
    with pytest.raises(HTTPException):
        studio.save_document_template_draft(created.id, studio.DraftSave(content=SIMPLE), db=db, user=world["foreign"])
    assert all(item.id != created.id for item in studio.list_document_templates(document_type=None, include_archived=True, db=db, user=world["foreign"]))
    brands = studio.list_document_brands(include_archived=False, db=db, user=world["admin"])
    with pytest.raises(HTTPException) as excinfo:
        studio.get_document_brand(brands[0].id, db=db, user=world["foreign"])
    assert excinfo.value.status_code == 404
    # Fremde Asset-ID im eigenen Brand-Profil wird abgelehnt
    with pytest.raises(HTTPException) as excinfo:
        studio.create_document_brand(studio.BrandCreate(name="X", tokens={"assets": {"logo": "0192f0aa-0000-7000-8000-00000000abcd"}}), db=db, user=world["admin"])
    assert excinfo.value.status_code == 422


def test_tenant_isolation_of_assets_components_assignments_and_revisions(db, world):
    """STUDIO-020: Fremde IDs für Assets, Komponenten, Zuweisungen und Revisionen ergeben 404/422,
    nie Zugriff auf Daten eines anderen Mandanten."""
    from app.models import DocumentAsset

    asset = DocumentAsset(tenant_id=world["tenant"].id, kind="image", category="image", name="Bild", storage_path="document_assets/x.png", mime_type="image/png")
    db.add(asset)
    db.flush()
    foreign = world["foreign"]
    for call in (
        lambda: studio.get_document_asset_content(asset.public_id, db=db, user=foreign),
        lambda: studio.get_document_asset_references(asset.public_id, db=db, user=foreign),
        lambda: studio.delete_document_asset(asset.public_id, db=db, user=foreign),
    ):
        with pytest.raises(HTTPException) as excinfo:
            call()
        assert excinfo.value.status_code == 404
    assert db.get(DocumentAsset, asset.id) is not None

    component = studio.create_document_component(studio.ComponentWrite(name="Kopf", node={"type": "spacer", "id": "s"}), db=db, user=world["writer"])
    for call in (
        lambda: studio.update_document_component(component.id, studio.ComponentWrite(name="Fremd"), db=db, user=foreign),
        lambda: studio.delete_document_component(component.id, db=db, user=foreign),
    ):
        with pytest.raises(HTTPException) as excinfo:
            call()
        assert excinfo.value.status_code == 404
    assert all(item.id != component.id for item in studio.list_document_components(db=db, user=foreign))

    # Zuweisung mit Protokollvorlage eines anderen Mandanten
    with pytest.raises(HTTPException) as excinfo:
        studio.set_document_template_assignment(studio.AssignmentWrite(document_type="protocol", protocol_template_id=world["protocol_template"].public_id), db=db, user=foreign)
    assert excinfo.value.status_code in (404, 422)

    created = _create(db, world)
    revisions = studio.list_document_template_revisions(created.id, db=db, user=world["writer"])
    with pytest.raises(HTTPException) as excinfo:
        studio.restore_document_template_revision(created.id, revisions[0].id, db=db, user=foreign)
    assert excinfo.value.status_code == 404
    with pytest.raises(HTTPException) as excinfo:
        studio.get_document_template_revision(created.id, revisions[0].id, db=db, user=foreign)
    assert excinfo.value.status_code == 404

    # Verweis auf die Komponente eines anderen Mandanten wird nicht aufgelöst
    alien = studio.create_document_component(studio.ComponentWrite(name="Fremd", node={"type": "spacer", "id": "f"}), db=db, user=foreign)
    referencing = {**SIMPLE, "body": [{"type": "component_ref", "id": "r", "component_id": str(alien.id)}]}
    saved = studio.save_document_template_draft(created.id, studio.DraftSave(content=referencing), db=db, user=world["writer"])
    assert [(item["node_id"], item["severity"]) for item in saved.diagnostics] == [("r", "error")]


def test_roles(db, world):
    with pytest.raises(HTTPException) as excinfo:
        _create(db, {**world, "writer": world["reader"]})
    assert excinfo.value.status_code == 403
    reader = studio.get_capabilities(user=world["reader"])
    assert reader["export"] and not reader["edit_templates"] and not reader["publish_templates"] and not reader["manage_brand"]
    assert studio.get_capabilities(user=world["admin"])["publish_templates"] is True
    with pytest.raises(HTTPException) as excinfo:
        studio.create_document_brand(studio.BrandCreate(name="X"), db=db, user=world["writer"])
    assert excinfo.value.status_code == 403


def test_brand_of_published_template_requires_publish_right(db, world):
    """STUDIO-003: Das Brand-Profil einer veröffentlichten Vorlage wirkt sofort auf Exporte -
    ändern darf es nur, wer auch veröffentlichen darf."""
    created = _create(db, world)
    brand = studio.create_document_brand(studio.BrandCreate(name="Anders", preset="forest"), db=db, user=world["admin"])
    # Unveröffentlicht: Schreibrolle darf das Profil wählen
    assert studio.update_document_template(created.id, studio.TemplateMetaUpdate(brand_id=brand.id), db=db, user=world["writer"]).brand_id == brand.id
    studio.publish_document_template(created.id, studio.PublishBody(), db=db, user=world["admin"])
    for body in (studio.TemplateMetaUpdate(clear_brand=True), studio.TemplateMetaUpdate(brand_id=brand.id)):
        with pytest.raises(HTTPException) as excinfo:
            studio.update_document_template(created.id, body, db=db, user=world["writer"])
        assert excinfo.value.status_code == 403
    # Name bleibt für die Schreibrolle änderbar
    assert studio.update_document_template(created.id, studio.TemplateMetaUpdate(name="Neu"), db=db, user=world["writer"]).name == "Neu"
    assert studio.update_document_template(created.id, studio.TemplateMetaUpdate(clear_brand=True), db=db, user=world["admin"]).brand_id is None


def test_brand_pinned_by_a_revision_cannot_be_deleted(db, world):
    """STUDIO-005: Eine mit «festhalten» veröffentlichte Revision verweist auf die
    Brand-Revision des damaligen Standardprofils; Löschen würde das Pinning still aufheben."""
    old_default = next(item for item in studio.list_document_brands(include_archived=False, db=db, user=world["admin"]) if item.is_default)
    created = _create(db, world)
    lock = created.draft_revision.lock_version
    studio.save_document_template_draft(created.id, studio.DraftSave(content=SIMPLE, lock_version=lock, brand_mode="pinned"), db=db, user=world["writer"])
    published = studio.publish_document_template(created.id, studio.PublishBody(), db=db, user=world["admin"])
    assert published.published_revision.brand_mode == "pinned"
    studio.create_document_brand(studio.BrandCreate(name="Neu", is_default=True), db=db, user=world["admin"])
    with pytest.raises(HTTPException) as excinfo:
        studio.delete_document_brand(old_default.id, db=db, user=world["admin"])
    assert excinfo.value.status_code in (409, 422)
    revision = db.scalar(select(DocumentTemplateRevision).where(DocumentTemplateRevision.public_id == published.published_revision.id))
    assert revision.brand_revision_id is not None


def test_assignment_priority_and_export_uses_it(db, world):
    created = _create(db, world)
    studio.publish_document_template(created.id, studio.PublishBody(), db=db, user=world["admin"])
    compact = db.query(DocumentTemplate).filter(DocumentTemplate.system_key == "protocol_compact").one()
    tenant_id = world["tenant"].id
    assert template_service.resolve_template(db, tenant_id, "protocol").source == "platform_default"
    studio.set_document_template_assignment(studio.AssignmentWrite(document_type="protocol", template_id=compact.public_id), db=db, user=world["admin"])
    assert template_service.resolve_template(db, tenant_id, "protocol").template.id == compact.id
    brand = studio.create_document_brand(studio.BrandCreate(name="Untergruppe", preset="forest"), db=db, user=world["admin"])
    studio.set_document_template_assignment(
        studio.AssignmentWrite(document_type="protocol", protocol_template_id=world["protocol_template"].public_id, template_id=created.id, brand_id=brand.id), db=db, user=world["admin"]
    )
    resolved = template_service.resolve_template(db, tenant_id, "protocol", protocol_template_id=world["protocol_template"].id)
    assert resolved.source == "protocol_template" and resolved.template.public_id == created.id
    result = asyncio.run(routes.render_document(DocumentRequest(protocol_id=world["protocol"].public_id), db=db, user=world["reader"]))
    assert result.template_id == created.id
    explicit = asyncio.run(routes.render_document(DocumentRequest(protocol_id=world["protocol"].public_id, template_id=compact.public_id), db=db, user=world["reader"]))
    assert explicit.template_id == compact.public_id
    with pytest.raises(HTTPException) as excinfo:
        studio.set_document_template_assignment(studio.AssignmentWrite(document_type="todos", template_id=compact.public_id), db=db, user=world["admin"])
    assert excinfo.value.status_code == 422
    assert {item.document_type for item in studio.list_document_template_assignments(db=db, user=world["reader"])} == {"protocol"}
    assert studio.set_document_template_assignment(studio.AssignmentWrite(document_type="protocol"), db=db, user=world["admin"]) is None
    assert template_service.resolve_template(db, tenant_id, "protocol").source == "platform_default"


def _protocol_template_assignment(db, world):
    created = _create(db, world)
    studio.publish_document_template(created.id, studio.PublishBody(), db=db, user=world["admin"])
    brand = studio.create_document_brand(studio.BrandCreate(name="Untergruppe", preset="forest"), db=db, user=world["admin"])
    studio.set_document_template_assignment(
        studio.AssignmentWrite(document_type="protocol", protocol_template_id=world["protocol_template"].public_id, template_id=created.id, brand_id=brand.id), db=db, user=world["admin"]
    )
    return created, brand


def test_duplicating_a_protocol_template_keeps_its_pdf_assignment(db, world):
    """STUDIO-012: Die Kopie einer Protokollvorlage übernimmt PDF-Vorlage und Brand-Profil."""
    from app.models import DocumentTemplateAssignment
    from app.services.template_service import TemplateService

    created, brand = _protocol_template_assignment(db, world)
    copy = TemplateService().duplicate_template(db, world["protocol_template"].id, new_name="Vorstand (Kopie)", created_by=None)
    row = db.scalar(select(DocumentTemplateAssignment).where(DocumentTemplateAssignment.protocol_template_id == copy.id))
    assert row is not None and row.document_type == "protocol"
    resolved = template_service.resolve_template(db, world["tenant"].id, "protocol", protocol_template_id=copy.id)
    assert resolved.source == "protocol_template" and resolved.template.public_id == created.id
    assert row.brand_id == db.scalar(select(studio.DocumentBrand.id).where(studio.DocumentBrand.public_id == brand.id))


def test_deleting_an_assigned_template_keeps_the_brand_assignment(db, world):
    """STUDIO-019: Wie beim Archivieren bleibt das Brand-Profil einer Zuweisung erhalten."""
    created, brand = _protocol_template_assignment(db, world)
    studio.delete_document_template(created.id, db=db, user=world["admin"])
    rows = studio.list_document_template_assignments(db=db, user=world["reader"])
    kept = [row for row in rows if row.protocol_template_id == world["protocol_template"].public_id]
    assert len(kept) == 1 and kept[0].template_id is None and kept[0].brand_id == brand.id


def test_archive_and_delete_rules(db, world):
    created = _create(db, world)
    studio.publish_document_template(created.id, studio.PublishBody(), db=db, user=world["admin"])
    asyncio.run(routes.render_document(DocumentRequest(protocol_id=world["protocol"].public_id, template_id=created.id), db=db, user=world["admin"]))
    with pytest.raises(HTTPException) as excinfo:
        studio.delete_document_template(created.id, db=db, user=world["admin"])
    assert excinfo.value.status_code == 422
    archived = studio.archive_document_template(created.id, studio.ArchiveBody(archived=True), db=db, user=world["admin"])
    assert archived.status == "archived"
    assert all(item.id != created.id for item in studio.list_document_templates(document_type="protocol", include_archived=False, db=db, user=world["reader"]))
    unused = _create(db, world)
    studio.delete_document_template(unused.id, db=db, user=world["admin"])
    with pytest.raises(HTTPException):
        studio.get_document_template(unused.id, db=db, user=world["admin"])


def test_brand_revisions_conflicts_and_defaults(db, world):
    default = studio.list_document_brands(include_archived=False, db=db, user=world["admin"])[0]
    assert default.is_default and default.revision == 1
    same = studio.update_document_brand(default.id, studio.BrandUpdate(lock_version=default.lock_version, tokens=default.tokens), db=db, user=world["admin"])
    assert same.revision == 1  # unveränderte Tokens erzeugen keine Revision
    changed = studio.update_document_brand(default.id, studio.BrandUpdate(lock_version=same.lock_version, tokens={**default.tokens, "colors": {**default.tokens["colors"], "primary": "#A83F2F"}}), db=db, user=world["admin"])
    assert changed.revision == 2 and changed.tokens["colors"]["primary"] == "#A83F2F"
    with pytest.raises(HTTPException) as excinfo:
        studio.update_document_brand(default.id, studio.BrandUpdate(lock_version=same.lock_version, name="Alt"), db=db, user=world["admin"])
    assert excinfo.value.status_code == 409
    revisions = studio.list_document_brand_revisions(default.id, db=db, user=world["admin"])
    restored = studio.restore_document_brand_revision(default.id, revisions[-1].id, db=db, user=world["admin"])
    assert restored.revision == 3 and restored.tokens["colors"]["primary"] == default.tokens["colors"]["primary"]
    with pytest.raises(HTTPException):
        studio.archive_document_brand(default.id, studio.ArchiveBody(archived=True), db=db, user=world["admin"])
    second = studio.create_document_brand(studio.BrandCreate(name="Zweit", from_brand_id=default.id), db=db, user=world["admin"])
    promoted = studio.update_document_brand(second.id, studio.BrandUpdate(lock_version=second.lock_version, is_default=True), db=db, user=world["admin"])
    assert promoted.is_default and not studio.get_document_brand(default.id, db=db, user=world["admin"]).is_default


def test_asset_upload_validation_and_usage(db, world, monkeypatch):
    from PIL import Image

    from app import scanner

    async def clean(contents, **kwargs):
        return ["clean" for _ in contents]

    monkeypatch.setattr(scanner, "scan_many", clean)
    bad = UploadFile(io.BytesIO(b"#let x = 1"), filename="evil.typ")
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(studio.upload_document_asset(kind="image", category="logo", name=None, file=bad, db=db, user=world["admin"]))
    assert excinfo.value.status_code == 422
    buffer = io.BytesIO()
    Image.new("RGB", (40, 20), (200, 10, 10)).save(buffer, format="PNG")
    upload = UploadFile(io.BytesIO(buffer.getvalue()), filename="logo.png", headers=Headers({"content-type": "image/png"}))
    asset = asyncio.run(studio.upload_document_asset(kind="image", category="logo", name="Logo", file=upload, db=db, user=world["admin"]))
    assert asset.category == "logo" and asset.width_px == 40
    brand = studio.list_document_brands(include_archived=False, db=db, user=world["admin"])[0]
    studio.update_document_brand(brand.id, studio.BrandUpdate(lock_version=brand.lock_version, tokens={**brand.tokens, "assets": {**brand.tokens["assets"], "logo": str(asset.id)}}), db=db, user=world["admin"])
    references = studio.get_document_asset_references(asset.id, db=db, user=world["admin"])
    assert references and references[0]["kind"] == "brand"
    with pytest.raises(HTTPException) as excinfo:
        studio.delete_document_asset(asset.id, db=db, user=world["admin"])
    assert excinfo.value.status_code == 422
    with pytest.raises(HTTPException):
        studio.get_document_asset_content(asset.id, db=db, user=world["foreign"])
    # Das Logo erscheint in der Vorschau einer Vorlage mit Logo-Kopf
    preview = asyncio.run(routes.preview_document(DocumentRequest(document_type="custom", data_mode="sample"), max_pages=1, db=db, user=world["writer"]))
    assert preview.pages


def test_reusable_components(db, world):
    component = studio.create_document_component(studio.ComponentWrite(name="Briefkopf", node={"type": "text", "id": "k", "content": {"default": [{"t": "bind", "path": "organization.name"}]}}), db=db, user=world["writer"])
    content = {"masters": [{"id": "default"}], "body": [{"type": "component_ref", "id": "ref", "component_id": str(component.id)}]}
    created = studio.create_document_template(studio.TemplateCreate(name="Mit Komponente", document_type="custom", content=content), db=db, user=world["writer"])
    assert created.diagnostics == []
    preview = asyncio.run(routes.preview_document(DocumentRequest(document_type="custom", content=content, data_mode="sample"), max_pages=1, db=db, user=world["writer"]))
    assert preview.diagnostics == []
    with pytest.raises(HTTPException) as excinfo:
        studio.delete_document_component(component.id, db=db, user=world["writer"])
    assert excinfo.value.status_code == 422
    with pytest.raises(HTTPException) as excinfo:
        studio.create_document_component(studio.ComponentWrite(name="Zirkel", node={"type": "component_ref", "id": "z", "component_id": str(component.id)}), db=db, user=world["writer"])
    assert excinfo.value.status_code == 422
    foreign = studio.create_document_template(studio.TemplateCreate(name="Fremd", document_type="custom", content=content), db=db, user=world["foreign"])
    assert [item["code"] for item in foreign.diagnostics] == ["componentNotFound"]


def test_catalog_and_thumbnail(db, world):
    catalog = studio.get_studio_catalog(db=db, user=world["reader"])
    assert {"node_types", "library", "data_components", "bindings", "document_types", "color_references", "fonts", "brand_presets"} <= set(catalog)
    # Schemas bleiben serverseitig (Validierung beim Speichern), der Katalog bleibt klein
    assert "content_schema" not in catalog and all("schema" not in meta for meta in catalog["node_types"].values())
    template = db.query(DocumentTemplate).filter(DocumentTemplate.system_key == "invitation_letter").one()
    response = asyncio.run(studio.get_document_template_thumbnail(template.public_id, db=db, user=world["reader"]))
    assert response.body.startswith(b"\x89PNG")
