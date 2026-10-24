"""Datenschutz-Audit PRIV-003/PRIV-004 (Umsetzungsplan Paket 2): Protokolle und Abgaben löschen ihre
Dateien vollständig mit - oder übernehmen abgewählte Dateien in die Galerie. Einzelne Einreichungen
lassen sich löschen; Dateien ohne jeden Bezug meldet das Systemmonitoring."""
from __future__ import annotations

import io
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi import HTTPException
from PIL import Image
from sqlalchemy import select

from app.api.routes import protocols as protocol_routes
from app.api.routes import submission_assignments as submission_routes
from app.core.storage import ABGABEBOX, MAIN, get_object_store
from app.models.entities import (
    GalleryImage,
    PhotoAlbum,
    PhotoAlbumItem,
    ProtocolImage,
    StoredFile,
    SubmissionAssignment,
    SubmissionUpload,
    SubmissionUploadFile,
)
from app.schemas.deletion import DeletionRequest
from app.services import storage_migration_service, system_health_service
from tests.factories import (
    make_current_user,
    make_list_definition,
    make_list_entry,
    make_protocol,
    make_protocol_element,
    make_protocol_element_block,
    make_template,
    make_tenant,
)


@pytest.fixture(autouse=True)
def _isolated_storage(monkeypatch, tmp_path):
    from app.core.config import settings

    monkeypatch.setattr(settings, "storage_root", str(tmp_path / "storage"))
    monkeypatch.setattr(settings, "upload_root", str(tmp_path / "storage" / "uploads"))
    monkeypatch.setattr(settings, "abgabebox_storage_root", str(tmp_path / "abgabebox"))
    monkeypatch.setattr(settings, "thumbnail_root", str(tmp_path / "thumbnails"))
    monkeypatch.setattr(settings, "storage_work_root", str(tmp_path / "work"))


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 6), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def _stored_file(db, tenant_id: int, key: str, *, namespace: str = MAIN, name: str = "bild.png") -> StoredFile:
    get_object_store().put_bytes(db, namespace, key, _png(), content_type="image/png")
    stored_file = StoredFile(tenant_id=tenant_id, original_name=name, mime_type="image/png", storage_path=key, scan_status="clean")
    db.add(stored_file)
    db.flush()
    return stored_file


def _gone(db, namespace: str, key: str) -> bool:
    storage_migration_service.purge_deleted_objects(db)
    return not get_object_store().exists(namespace, key)


def _protocol_with_image(db, tenant_id: int, template_id: int, number: str, stored_file: StoredFile):
    protocol = make_protocol(db, tenant_id, template_id, protocol_number=number, status="geplant")
    element = make_protocol_element(db, protocol.id)
    block = make_protocol_element_block(db, element.id, configuration_snapshot_json={})
    db.add(ProtocolImage(protocol_element_block_id=block.id, stored_file_id=stored_file.id, title="Gruppenfoto"))
    db.flush()
    return protocol


# ── Protokolle ─────────────────────────────────────────────────────────────────────────────


def test_protocol_deletion_removes_its_images_by_default(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    image = _stored_file(db, tenant.id, "uploads/p1.png")
    protocol = _protocol_with_image(db, tenant.id, template.id, "P-1", image)
    image_id, key = image.id, image.storage_path
    user = make_current_user(tenant.id, role="writer")

    preview = protocol_routes.preview_protocol_deletion(protocol.public_id, db, user)
    assert [(f.name, f.used_elsewhere, f.label) for f in preview.files] == [("bild.png", False, "Gruppenfoto")]

    protocol_routes.delete_protocol(protocol.public_id, db, user)

    assert db.get(StoredFile, image_id) is None
    assert _gone(db, MAIN, key)


def test_unselected_protocol_image_moves_to_gallery(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    image = _stored_file(db, tenant.id, "uploads/p2.png")
    protocol = _protocol_with_image(db, tenant.id, template.id, "P-2", image)
    user = make_current_user(tenant.id, role="writer")

    result = protocol_routes.delete_protocol_with_selection(protocol.public_id, DeletionRequest(delete_file_ids=[]), db, user)

    assert (result.deleted_files, result.kept_files) == (0, 1)
    kept = db.get(StoredFile, image.id)
    assert kept is not None and "Protokoll P-2" in kept.tags
    assert db.scalar(select(GalleryImage.id).where(GalleryImage.stored_file_id == image.id)) is not None
    assert get_object_store().exists(MAIN, kept.storage_path)


def test_image_shared_with_another_protocol_is_untouched(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    image = _stored_file(db, tenant.id, "uploads/p3.png")
    protocol = _protocol_with_image(db, tenant.id, template.id, "P-3", image)
    _protocol_with_image(db, tenant.id, template.id, "P-4", image)
    user = make_current_user(tenant.id, role="writer")

    preview = protocol_routes.preview_protocol_deletion(protocol.public_id, db, user)
    assert preview.files[0].used_elsewhere is True
    result = protocol_routes.delete_protocol_with_selection(protocol.public_id, DeletionRequest(delete_file_ids=[image.public_id]), db, user)

    assert result.untouched_files == 1
    assert db.get(StoredFile, image.id) is not None


def test_protocol_of_another_tenant_is_not_found(db):
    tenant = make_tenant(db)
    other = make_tenant(db, "Fremd")
    template = make_template(db, tenant.id)
    protocol = _protocol_with_image(db, tenant.id, template.id, "P-5", _stored_file(db, tenant.id, "uploads/p5.png"))

    with pytest.raises(HTTPException) as exc:
        protocol_routes.preview_protocol_deletion(protocol.public_id, db, make_current_user(other.id, role="admin"))
    assert exc.value.status_code == 404


# ── Abgaben ────────────────────────────────────────────────────────────────────────────────


def _assignment_with_upload(db, tenant_id: int, slug: str):
    definition = make_list_definition(db, tenant_id)
    entry = make_list_entry(db, definition.id)
    assignment = SubmissionAssignment(
        tenant_id=tenant_id, title="Arztzeugnisse", public_slug=slug,
        source_type="list", list_definition_id=definition.id, deadline=date(2026, 1, 1),
    )
    db.add(assignment)
    db.flush()
    upload = SubmissionUpload(assignment_id=assignment.id, list_entry_id=entry.id, status="submitted", submitted_at=datetime.now(UTC))
    db.add(upload)
    db.flush()
    stored_file = _stored_file(db, tenant_id, f"{slug}/zeugnis.png", namespace=ABGABEBOX, name="zeugnis.png")
    upload_file = SubmissionUploadFile(upload_id=upload.id, stored_file_id=stored_file.id)
    db.add(upload_file)
    db.flush()
    return assignment, upload, upload_file, stored_file


def test_assignment_deletion_removes_submitted_files(db):
    tenant = make_tenant(db)
    assignment, _upload, _upload_file, stored_file = _assignment_with_upload(db, tenant.id, "abgabe-a")
    stored_id, key = stored_file.id, stored_file.storage_path
    user = make_current_user(tenant.id, role="admin")

    preview = submission_routes.preview_assignment_deletion(assignment.public_id, db, user)
    assert [(f.group, f.name) for f in preview.files] == [("submission", "zeugnis.png")]
    submission_routes.delete_assignment(assignment.public_id, db, user)

    assert db.get(StoredFile, stored_id) is None
    assert _gone(db, ABGABEBOX, key)


def test_kept_submission_file_moves_to_gallery_and_main_storage(db):
    tenant = make_tenant(db)
    assignment, _upload, upload_file, stored_file = _assignment_with_upload(db, tenant.id, "abgabe-b")
    old_key = stored_file.storage_path
    album = PhotoAlbum(tenant_id=tenant.id, name="Lager", kind="manual")
    db.add(album)
    db.flush()
    db.add(PhotoAlbumItem(album_id=album.id, file_id=upload_file.public_id))
    db.flush()
    user = make_current_user(tenant.id, role="admin")

    result = submission_routes.delete_assignment_with_selection(assignment.public_id, DeletionRequest(delete_file_ids=[]), db, user)

    assert result.kept_files == 1
    kept = db.get(StoredFile, stored_file.id)
    assert kept.storage_path != old_key
    assert get_object_store().exists(MAIN, kept.storage_path)
    assert _gone(db, ABGABEBOX, old_key)
    assert "Abgabe Arztzeugnisse" in kept.tags
    assert db.scalar(select(GalleryImage.id).where(GalleryImage.stored_file_id == kept.id)) is not None
    assert db.scalar(select(PhotoAlbumItem.file_id).where(PhotoAlbumItem.album_id == album.id)) == kept.public_id


def test_single_submitted_file_can_be_deleted(db):
    tenant = make_tenant(db)
    _assignment, upload, _upload_file, stored_file = _assignment_with_upload(db, tenant.id, "abgabe-c")
    stored_id, upload_id = stored_file.id, upload.id
    user = make_current_user(tenant.id, role="admin")

    submission_routes.delete_submission_file(upload.public_id, stored_file.public_id, db, user)

    assert db.get(StoredFile, stored_id) is None
    assert db.get(SubmissionUpload, upload_id) is None  # leer gewordene Einreichung verschwindet


def test_submitted_file_of_another_tenant_cannot_be_deleted(db):
    tenant = make_tenant(db)
    other = make_tenant(db, "Fremd")
    _assignment, upload, _upload_file, stored_file = _assignment_with_upload(db, tenant.id, "abgabe-d")

    with pytest.raises(HTTPException) as exc:
        submission_routes.delete_submission_file(upload.public_id, stored_file.public_id, db, make_current_user(other.id, role="admin"))
    assert exc.value.status_code == 404
    assert db.get(StoredFile, stored_file.id) is not None


# ── Verwaiste Dateien ──────────────────────────────────────────────────────────────────────


def test_orphaned_files_are_reported(db):
    tenant = make_tenant(db)
    before = system_health_service._check_orphaned_files(db).params["count"]
    orphan = _stored_file(db, tenant.id, "uploads/orphan.png")
    orphan.created_at = datetime.now(UTC) - timedelta(days=2)
    db.flush()

    check = system_health_service._check_orphaned_files(db)

    assert check.params["count"] == before + 1
    assert check.status == "warning"
