"""Tests for the Fotos page's multi-select bulk actions: FileService.delete_gallery_images/
bulk_update_tags and their routes (POST /files/bulk-delete, /files/bulk-tags,
PATCH /files/{file_id}/best). delete_gallery_images only ever hard-deletes gallery
uploads - protocol images, word-import source documents and submission uploads each have
their own deletion semantics this must not bypass (see the function's docstring)."""

import asyncio
import io
import uuid
from datetime import date
from pathlib import Path

import pytest
from fastapi import HTTPException
from PIL import Image

from app.api.routes import files as files_routes
from app.core.config import settings
from app.models.entities import PhotoAlbum, PhotoAlbumItem, ProtocolImage, StoredFile
from app.schemas.files import FileBulkDelete, FileBulkTagsUpdate, PhotoAlbumItemBestUpdate
from app.services import photo_album_service
from app.services.file_service import FileService
from tests.factories import (
    make_current_user,
    make_protocol,
    make_protocol_element,
    make_protocol_element_block,
    make_template,
    make_tenant,
)

service = FileService()


@pytest.fixture(autouse=True)
def _isolated_storage_root(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(settings, "upload_root", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "thumbnail_root", str(tmp_path / "thumbnails"))


def _png_bytes(color=(10, 20, 30)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (48, 48), color=color).save(buffer, format="PNG")
    return buffer.getvalue()


def _upload_gallery_image(db, tenant_id: int, name: str = "a.png"):
    items, errors = asyncio.run(service.save_gallery_uploads(db, tenant_id=tenant_id, files=[(name, _png_bytes())], tags=[], created_by=None))
    assert errors == []
    db.commit()
    return items[0]


def _make_protocol_image(db, tenant_id: int):
    template = make_template(db, tenant_id)
    protocol = make_protocol(db, tenant_id, template.id, protocol_number="1/2026", protocol_date=date(2026, 1, 1))
    element = make_protocol_element(db, protocol.id)
    block = make_protocol_element_block(db, element.id, configuration_snapshot_json={})
    stored_file = StoredFile(
        tenant_id=tenant_id, original_name="protokoll-bild.png", mime_type="image/png",
        storage_path="uploads/tenant-x/block-x/protokoll-bild.png", scan_status="clean",
    )
    db.add(stored_file)
    db.flush()
    db.add(ProtocolImage(protocol_element_block_id=block.id, stored_file_id=stored_file.id, sort_index=0))
    db.flush()
    return stored_file


def test_delete_gallery_images_removes_row_and_disk_files(db):
    tenant = make_tenant(db)
    item = _upload_gallery_image(db, tenant.id)
    stored_file = service.stored_file_repository.get_by_public_id(db, item.id, tenant_id=tenant.id)
    disk_path = Path(settings.storage_root) / stored_file.storage_path
    assert disk_path.exists()

    deleted, errors = service.delete_gallery_images(db, tenant.id, [item.id])
    db.commit()

    assert deleted == [item.id]
    assert errors == []
    assert service.stored_file_repository.get_by_public_id(db, item.id, tenant_id=tenant.id) is None
    assert not disk_path.exists()


def test_delete_gallery_images_refuses_non_gallery_sources(db):
    tenant = make_tenant(db)
    stored_file = _make_protocol_image(db, tenant.id)
    db.commit()

    deleted, errors = service.delete_gallery_images(db, tenant.id, [stored_file.public_id])

    assert deleted == []
    assert len(errors) == 1
    assert "protokoll-bild.png" in errors[0]
    assert service.stored_file_repository.get(db, stored_file.id) is not None


def test_delete_gallery_images_reports_unknown_or_cross_tenant_id_as_an_error(db):
    tenant_a = make_tenant(db)
    tenant_b = make_tenant(db)
    item = _upload_gallery_image(db, tenant_b.id)

    deleted, errors = service.delete_gallery_images(db, tenant_a.id, [item.id])

    assert deleted == []
    assert len(errors) == 1
    assert service.stored_file_repository.get_by_public_id(db, item.id, tenant_id=tenant_b.id) is not None


def test_delete_gallery_images_removes_album_membership_when_paired_with_drop_items_for_files(db):
    """Mirrors the bulk-delete route's own sequencing: drop_items_for_files first (no FK
    protects photo_album_item.file_id), then delete_gallery_images, then recompute_best_of
    on whatever albums lost an item."""
    tenant = make_tenant(db)
    item = _upload_gallery_image(db, tenant.id)
    album = PhotoAlbum(tenant_id=tenant.id, name="Album", kind="manual")
    db.add(album)
    db.flush()
    photo_album_service.add_items(db, album, [item.id])
    db.commit()

    touched = photo_album_service.drop_items_for_files(db, [item.id])
    deleted, errors = service.delete_gallery_images(db, tenant.id, [item.id])
    db.commit()
    for album_id in touched:
        recomputed_album = db.get(PhotoAlbum, album_id)
        if recomputed_album is not None:
            photo_album_service.recompute_best_of(db, service, recomputed_album)

    assert deleted == [item.id]
    assert touched == {album.id}
    assert db.query(PhotoAlbumItem).filter_by(album_id=album.id).count() == 0


def test_bulk_update_tags_adds_and_removes(db):
    tenant = make_tenant(db)
    item = _upload_gallery_image(db, tenant.id)
    service.bulk_update_tags(db, tenant.id, [item.id], ["Sommerlager"], [])

    stored_file = service.stored_file_repository.get_by_public_id(db, item.id, tenant_id=tenant.id)
    assert stored_file.tags == ["Sommerlager"]

    service.bulk_update_tags(db, tenant.id, [item.id], ["Best-of"], ["Sommerlager"])
    db.refresh(stored_file)
    assert stored_file.tags == ["Best-of"]


def test_bulk_delete_route_requires_writer_role(db):
    tenant = make_tenant(db)
    user = make_current_user(tenant.id, role="reader")

    with pytest.raises(HTTPException) as exc_info:
        files_routes.bulk_delete_files(FileBulkDelete(file_ids=[]), db=db, user=user)
    assert exc_info.value.status_code == 403


def test_bulk_delete_route_rejects_more_than_200_ids(db):
    tenant = make_tenant(db)
    user = make_current_user(tenant.id, role="writer")
    ids = [uuid.uuid4() for _ in range(201)]

    with pytest.raises(HTTPException) as exc_info:
        files_routes.bulk_delete_files(FileBulkDelete(file_ids=ids), db=db, user=user)
    assert exc_info.value.status_code == 422


def test_bulk_delete_route_deletes_and_cleans_up_album(db):
    tenant = make_tenant(db)
    item = _upload_gallery_image(db, tenant.id)
    album = PhotoAlbum(tenant_id=tenant.id, name="Album", kind="manual")
    db.add(album)
    db.flush()
    photo_album_service.add_items(db, album, [item.id])
    db.commit()
    user = make_current_user(tenant.id, role="writer")

    result = files_routes.bulk_delete_files(FileBulkDelete(file_ids=[item.id]), db=db, user=user)

    assert result.deleted_ids == [item.id]
    assert result.errors == []
    assert db.query(PhotoAlbumItem).filter_by(album_id=album.id).count() == 0


def test_set_file_best_everywhere_route_422_when_photo_has_no_album(db):
    tenant = make_tenant(db)
    item = _upload_gallery_image(db, tenant.id)
    user = make_current_user(tenant.id, role="writer")

    with pytest.raises(HTTPException) as exc_info:
        files_routes.set_file_best_everywhere(item.id, PhotoAlbumItemBestUpdate(best_override="include"), db=db, user=user)
    assert exc_info.value.status_code == 422


def test_set_file_best_everywhere_route_succeeds_when_photo_is_in_an_album(db):
    tenant = make_tenant(db)
    item = _upload_gallery_image(db, tenant.id)
    album = PhotoAlbum(tenant_id=tenant.id, name="Album", kind="manual")
    db.add(album)
    db.flush()
    photo_album_service.add_items(db, album, [item.id])
    db.commit()
    user = make_current_user(tenant.id, role="writer")

    files_routes.set_file_best_everywhere(item.id, PhotoAlbumItemBestUpdate(best_override="include"), db=db, user=user)

    row = db.get(PhotoAlbumItem, {"album_id": album.id, "file_id": item.id})
    assert row.is_best is True


def test_bulk_update_tags_route_requires_writer_role(db):
    tenant = make_tenant(db)
    user = make_current_user(tenant.id, role="reader")

    with pytest.raises(HTTPException) as exc_info:
        files_routes.bulk_update_file_tags(FileBulkTagsUpdate(file_ids=[]), db=db, user=user)
    assert exc_info.value.status_code == 403
