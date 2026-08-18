"""Thumbnail generation for the "Dateien" grid: FileService.ensure_thumbnail (lazy
backfill/generation for any StoredFile) and eager generation in save_protocol_image, plus
the thumbnail_url derivation in list_tenant_files. Same isolated-storage-root convention as
test_protocol_image_duplicate_check.py so no files are left behind on the real bind mount.
"""
import asyncio
import io
from pathlib import Path

import pytest
from PIL import Image
from starlette.datastructures import Headers

from fastapi import UploadFile

from app.models.entities import StoredFile
from app.services.file_service import FileService, _safe_storage_path
from tests.factories import make_protocol, make_protocol_element, make_protocol_element_block, make_template, make_tenant


@pytest.fixture(autouse=True)
def _isolated_storage_root(monkeypatch, tmp_path):
    from app.core.config import settings

    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(settings, "upload_root", str(tmp_path / "uploads"))


def _png_bytes(color: tuple[int, int, int] = (10, 20, 30), size: tuple[int, int] = (800, 600)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color=color).save(buffer, format="PNG")
    return buffer.getvalue()


def _upload_file(content: bytes, filename: str = "image.png", content_type: str = "image/png") -> UploadFile:
    return UploadFile(file=io.BytesIO(content), filename=filename, headers=Headers({"content-type": content_type}))


def _make_block(db, tenant_id: int):
    template = make_template(db, tenant_id)
    protocol = make_protocol(db, tenant_id, template.id)
    element = make_protocol_element(db, protocol.id)
    return make_protocol_element_block(db, element.id, configuration_snapshot_json={})


def test_save_protocol_image_eagerly_generates_a_thumbnail(db):
    from app.core.config import settings

    tenant = make_tenant(db)
    block = _make_block(db, tenant.id)
    service = FileService()

    result = asyncio.run(service.save_protocol_image(db, protocol_element_block=block, file=_upload_file(_png_bytes())))

    stored_file = db.get(StoredFile, result.stored_file_id)
    assert stored_file.thumbnail_path is not None
    thumb_path = _safe_storage_path(settings.storage_root, stored_file.thumbnail_path)
    assert thumb_path.exists()
    with Image.open(thumb_path) as thumb:
        assert max(thumb.size) <= 480


def test_ensure_thumbnail_backfills_a_stored_file_created_without_one(db):
    """Simulates a pre-existing StoredFile row (e.g. one written by abgabebox-backend's
    restricted DB role, or created before this feature existed) that has no thumbnail_path
    yet - the first request must generate and persist one."""
    from app.core.config import settings

    tenant = make_tenant(db)
    original_path = Path(settings.storage_root) / "original.png"
    original_path.parent.mkdir(parents=True, exist_ok=True)
    original_path.write_bytes(_png_bytes(color=(50, 60, 70)))

    stored_file = StoredFile(
        tenant_id=tenant.id, original_name="original.png", mime_type="image/png",
        storage_path="original.png",
    )
    db.add(stored_file)
    db.flush()
    assert stored_file.thumbnail_path is None

    service = FileService()
    thumb_path = service.ensure_thumbnail(db, stored_file, settings.storage_root)

    assert thumb_path is not None
    assert thumb_path.exists()
    assert stored_file.thumbnail_path is not None

    # Second call must reuse the persisted thumbnail instead of regenerating it.
    thumb_path_again = service.ensure_thumbnail(db, stored_file, settings.storage_root)
    assert thumb_path_again == thumb_path


def test_ensure_thumbnail_returns_none_for_non_image_mime(db):
    from app.core.config import settings

    tenant = make_tenant(db)
    stored_file = StoredFile(
        tenant_id=tenant.id, original_name="doc.pdf", mime_type="application/pdf",
        storage_path="doc.pdf",
    )
    db.add(stored_file)
    db.flush()

    service = FileService()
    assert service.ensure_thumbnail(db, stored_file, settings.storage_root) is None
    assert stored_file.thumbnail_path is None


def test_list_tenant_files_sets_thumbnail_url_only_for_images(db):
    tenant = make_tenant(db)
    block = _make_block(db, tenant.id)
    service = FileService()
    result = asyncio.run(service.save_protocol_image(db, protocol_element_block=block, file=_upload_file(_png_bytes())))

    items = service.list_tenant_files(db, tenant.id)

    assert len(items) == 1
    item = items[0]
    assert item.is_image is True
    assert item.thumbnail_url == f"/api/stored-files/{result.stored_file_id}/thumbnail"
