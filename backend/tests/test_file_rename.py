"""Datei umbenennen (Datei-Detail v2): PATCH /api/stored-files/{id}/name ändert nur den
Anzeigenamen - Rechte wie beim Tag-Speichern, Mandantentrennung, Endung bleibt, Audit, Dokumentname
folgt; der Verlauf nennt, wer eine Version hochgeladen hat."""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import text

from app.api.routes import files as files_routes
from app.models import StoredFile
from app.models.entities import GalleryImage
from app.schemas.files import StoredFileRename
from app.services import document_read_service, document_service
from tests.document_support import document_storage, gallery_document  # noqa: F401
from tests.factories import make_app_user, make_current_user, make_tenant


def _user(db, tenant_id: int, role: str = "writer", **kwargs):
    account = make_app_user(db, email=f"rename-{uuid.uuid4().hex[:8]}@example.com", tenant_id=tenant_id, role_code=role)
    return make_current_user(tenant_id, role=role, user_id=account.id, **kwargs)


def _rename(db, user, stored_file, name: str):
    return files_routes.rename_stored_file(stored_file.public_id, StoredFileRename(name=name), db, user)


def _image(db, tenant_id: int) -> StoredFile:
    stored_file = StoredFile(
        tenant_id=tenant_id, original_name="strand.png", mime_type="image/png",
        storage_path=f"uploads/tenant-x/gallery/{uuid.uuid4().hex}.png", scan_status="clean",
    )
    db.add(stored_file)
    db.flush()
    db.add(GalleryImage(tenant_id=tenant_id, stored_file_id=stored_file.id))
    db.flush()
    return stored_file


def test_rename_keeps_extension_updates_document_and_audits(db, document_storage):
    tenant = make_tenant(db)
    user = _user(db, tenant.id)
    stored_file = gallery_document(db, tenant.id, "sample.docx")
    document = document_service.register_upload(db, stored_file)
    storage_path = stored_file.storage_path

    result = _rename(db, user, stored_file, "  Jahresbericht 2026  ")

    assert result.original_name == "Jahresbericht 2026.docx"
    db.refresh(stored_file)
    db.refresh(document)
    assert stored_file.original_name == "Jahresbericht 2026.docx"
    assert stored_file.storage_path == storage_path
    assert document.display_name == "Jahresbericht 2026.docx"
    actions = set(db.scalars(text("SELECT action FROM audit_log WHERE tenant_id = :t"), {"t": tenant.id}))
    assert "file.renamed" in actions


def test_rename_accepts_name_with_extension_in_other_case(db, document_storage):
    tenant = make_tenant(db)
    stored_file = gallery_document(db, tenant.id, "sample.docx")
    result = _rename(db, _user(db, tenant.id), stored_file, "Bericht.DOCX")
    assert result.original_name == "Bericht.docx"


def test_rename_requires_manage_permission(db, document_storage):
    tenant = make_tenant(db)
    stored_file = gallery_document(db, tenant.id, "sample.docx")
    with pytest.raises(HTTPException) as exc:
        _rename(db, _user(db, tenant.id, role="reader"), stored_file, "Neu")
    assert exc.value.status_code == 403


def test_rename_image_needs_photos_manage(db):
    tenant = make_tenant(db)
    stored_file = _image(db, tenant.id)
    user = _user(db, tenant.id, permissions=frozenset({"files.manage", "files.read", "photos.read", "meetings.read"}))
    with pytest.raises(HTTPException) as exc:
        _rename(db, user, stored_file, "Strand")
    assert exc.value.status_code == 403


def test_rename_of_other_tenants_file_is_not_found(db, document_storage):
    own = make_tenant(db)
    other = make_tenant(db)
    foreign = gallery_document(db, other.id, "sample.docx")
    with pytest.raises(HTTPException) as exc:
        _rename(db, _user(db, own.id), foreign, "Übernommen")
    assert exc.value.status_code == 404
    db.refresh(foreign)
    assert foreign.original_name == "sample.docx"


@pytest.mark.parametrize("name", ["", "   ", "a/b", "a\\b", "zeile\numbruch", "nul\x00", ".", "x" * 201])
def test_rename_rejects_invalid_names(name):
    with pytest.raises(ValidationError):
        StoredFileRename(name=name)


def test_document_detail_names_version_uploader(db, document_storage):
    tenant = make_tenant(db)
    account = make_app_user(db, email=f"uploader-{uuid.uuid4().hex[:8]}@example.com", tenant_id=tenant.id, role_code="writer")
    stored_file = gallery_document(db, tenant.id, "sample.docx", created_by=account.id)
    document = document_service.register_upload(db, stored_file)
    detail = document_read_service.build_detail(db, document, can_write=False)
    assert detail.versions[0].created_by_name == account.display_name
