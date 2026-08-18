"""Tests for the file-detail metadata endpoint (GET .../metadata, image dimensions/EXIF via
FileService.get_stored_file_metadata / _extract_image_metadata) and the tags endpoints on the
submission-upload side (routes/submission_assignments.py) - the stored-files-side tags route
is covered in test_files_overview.py alongside the rest of StoredFileRepository/FileService.
Same isolated-storage-root convention as test_file_thumbnails.py so no files are left behind
on the real bind mount.
"""
import io
from datetime import date

import pytest
from fastapi import HTTPException
from PIL import Image

from app.api.routes import files as files_routes
from app.api.routes import submission_assignments as submission_routes
from app.models.entities import StoredFile, SubmissionAssignment, SubmissionUpload, SubmissionUploadFile
from app.services.file_service import FileService, _extract_image_metadata
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

service = FileService()


@pytest.fixture(autouse=True)
def _isolated_storage_root(monkeypatch, tmp_path):
    from app.core.config import settings

    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(settings, "upload_root", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "abgabebox_storage_root", str(tmp_path / "abgabebox"))


def _png_bytes(size: tuple[int, int] = (640, 480)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color=(10, 20, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


def _write_file(root: str, relative_path: str, content: bytes) -> None:
    from pathlib import Path

    path = Path(root) / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _make_protocol_image_file(db, tenant_id, *, size=(640, 480)):
    from app.core.config import settings
    from app.models.entities import ProtocolImage

    template = make_template(db, tenant_id)
    protocol = make_protocol(db, tenant_id, template.id, protocol_number="9/2026", protocol_date=date(2026, 5, 1))
    element = make_protocol_element(db, protocol.id)
    block = make_protocol_element_block(db, element.id, configuration_snapshot_json={})
    relative_path = "uploads/tenant-x/block-x/foto.png"
    content = _png_bytes(size)
    _write_file(settings.storage_root, relative_path, content)
    stored_file = StoredFile(
        tenant_id=tenant_id, original_name="foto.png", mime_type="image/png",
        storage_path=relative_path, file_size_bytes=len(content),
    )
    db.add(stored_file)
    db.flush()
    db.add(ProtocolImage(protocol_element_block_id=block.id, stored_file_id=stored_file.id, sort_index=0))
    db.flush()
    return protocol, stored_file


def _make_submission_upload_image(db, tenant_id, *, size=(320, 240)):
    from app.core.config import settings

    list_definition = make_list_definition(db, tenant_id)
    entry = make_list_entry(db, list_definition.id)
    assignment = SubmissionAssignment(
        tenant_id=tenant_id, title="Fotos Sommerlager", public_slug="fotos-sola-meta",
        source_type="list", list_definition_id=list_definition.id,
    )
    db.add(assignment)
    db.flush()
    upload = SubmissionUpload(assignment_id=assignment.id, list_entry_id=entry.id, status="submitted")
    db.add(upload)
    db.flush()
    relative_path = "foto.png"
    content = _png_bytes(size)
    _write_file(settings.abgabebox_storage_root, relative_path, content)
    stored_file = StoredFile(tenant_id=tenant_id, original_name="foto.png", mime_type="image/png", storage_path=relative_path, file_size_bytes=len(content))
    db.add(stored_file)
    db.flush()
    db.add(SubmissionUploadFile(upload_id=upload.id, stored_file_id=stored_file.id))
    db.flush()
    return assignment, upload, stored_file


def test_extract_image_metadata_reads_dimensions_and_skips_missing_exif():
    width, height, taken_at, camera = _extract_image_metadata(_png_bytes((100, 50)))

    assert (width, height) == (100, 50)
    assert taken_at is None
    assert camera is None


def test_extract_image_metadata_returns_none_for_undecodable_content():
    assert _extract_image_metadata(b"not an image") == (None, None, None, None)


def test_get_stored_file_metadata_includes_dimensions_for_protocol_image(db):
    from app.core.config import settings

    tenant = make_tenant(db)
    protocol, stored_file = _make_protocol_image_file(db, tenant.id, size=(640, 480))

    metadata = service.get_stored_file_metadata(db, stored_file, settings.storage_root, tenant.id)

    assert metadata is not None
    assert (metadata.width, metadata.height) == (640, 480)
    assert metadata.source == "protocol_image"
    assert metadata.ref_label == "9/2026"
    assert metadata.origin_tag.startswith("Protokoll 9/2026")


def test_get_stored_file_metadata_returns_none_for_files_outside_the_overview(db):
    from app.core.config import settings

    tenant = make_tenant(db)
    stored_file = StoredFile(tenant_id=tenant.id, original_name="logo.png", mime_type="image/png", storage_path="logo.png")
    db.add(stored_file)
    db.flush()

    assert service.get_stored_file_metadata(db, stored_file, settings.storage_root, tenant.id) is None


def test_get_stored_file_metadata_route_requires_reader_role(db):
    tenant = make_tenant(db)
    _, stored_file = _make_protocol_image_file(db, tenant.id)
    no_role_user = make_current_user(tenant.id, role=None)

    with pytest.raises(HTTPException) as exc_info:
        files_routes.get_stored_file_metadata(stored_file.id, db=db, user=no_role_user)
    assert exc_info.value.status_code == 403


def test_get_stored_file_metadata_route_returns_dimensions_for_writer(db):
    tenant = make_tenant(db)
    _, stored_file = _make_protocol_image_file(db, tenant.id, size=(200, 100))
    writer = make_current_user(tenant.id, role="writer")

    metadata = files_routes.get_stored_file_metadata(stored_file.id, db=db, user=writer)

    assert (metadata.width, metadata.height) == (200, 100)


def test_update_submission_file_tags_route_requires_writer_role(db):
    tenant = make_tenant(db)
    _, upload, stored_file = _make_submission_upload_image(db, tenant.id)
    reader = make_current_user(tenant.id, role="reader")

    with pytest.raises(HTTPException) as exc_info:
        submission_routes.update_submission_file_tags(
            upload.id, stored_file.id, submission_routes.StoredFileTagsUpdate(tags=["Sonne"]), db=db, user=reader,
        )
    assert exc_info.value.status_code == 403


def test_update_submission_file_tags_route_persists_for_writer_role(db):
    tenant = make_tenant(db)
    _, upload, stored_file = _make_submission_upload_image(db, tenant.id)
    writer = make_current_user(tenant.id, role="writer")

    result = submission_routes.update_submission_file_tags(
        upload.id, stored_file.id, submission_routes.StoredFileTagsUpdate(tags=["Sonne"]), db=db, user=writer,
    )

    assert result == ["Sonne"]
    db.refresh(stored_file)
    assert stored_file.tags == ["Sonne"]


def test_update_submission_file_tags_route_rejects_other_tenant(db):
    tenant_a = make_tenant(db, "Tenant A")
    tenant_b = make_tenant(db, "Tenant B")
    _, upload, stored_file = _make_submission_upload_image(db, tenant_a.id)
    writer_b = make_current_user(tenant_b.id, role="writer")

    with pytest.raises(HTTPException) as exc_info:
        submission_routes.update_submission_file_tags(
            upload.id, stored_file.id, submission_routes.StoredFileTagsUpdate(tags=["Sonne"]), db=db, user=writer_b,
        )
    assert exc_info.value.status_code == 404


def test_get_submission_file_metadata_route_returns_dimensions(db):
    tenant = make_tenant(db)
    assignment, upload, stored_file = _make_submission_upload_image(db, tenant.id, size=(150, 75))
    writer = make_current_user(tenant.id, role="writer")

    metadata = submission_routes.get_submission_file_metadata(upload.id, stored_file.id, db=db, user=writer)

    assert (metadata.width, metadata.height) == (150, 75)
    assert metadata.source == "submission_upload"
    assert metadata.origin_tag == f"Abgabe: {assignment.title}"
