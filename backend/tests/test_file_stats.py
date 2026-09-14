"""Tests for FileService.file_stats - the Dateien page's Dokumente/Fotos/Speicher stat
cards. Deliberately built from the same files-overview union list_tenant_files itself
lists (not storage_service's admin-only, per-origin-table breakdown), so these numbers
must always match what the page actually shows."""

import pytest
from fastapi import HTTPException

from app.api.routes import files as files_routes
from app.models.entities import GalleryImage, StoredFile
from app.services.file_service import FileService
from tests.factories import make_current_user, make_tenant

service = FileService()


def _make_gallery_image(db, tenant_id, *, mime_type="image/png", scan_status="clean", file_size_bytes=1000):
    stored_file = StoredFile(
        tenant_id=tenant_id, original_name="datei", mime_type=mime_type,
        storage_path="uploads/tenant-x/gallery/datei", scan_status=scan_status, file_size_bytes=file_size_bytes,
    )
    db.add(stored_file)
    db.flush()
    db.add(GalleryImage(tenant_id=tenant_id, stored_file_id=stored_file.id))
    db.flush()
    return stored_file


def test_file_stats_splits_photos_and_documents_and_sums_bytes(db):
    tenant = make_tenant(db)
    _make_gallery_image(db, tenant.id, mime_type="image/png", file_size_bytes=1000)
    _make_gallery_image(db, tenant.id, mime_type="image/jpeg", file_size_bytes=2000)
    _make_gallery_image(db, tenant.id, mime_type="application/pdf", file_size_bytes=500)
    db.commit()

    stats = service.file_stats(db, tenant.id)

    assert stats.photo_count == 2
    assert stats.document_count == 1
    assert stats.total_bytes == 3500


def test_file_stats_treats_missing_mime_type_as_a_document(db):
    tenant = make_tenant(db)
    _make_gallery_image(db, tenant.id, mime_type=None)
    db.commit()

    stats = service.file_stats(db, tenant.id)

    assert stats.photo_count == 0
    assert stats.document_count == 1


def test_file_stats_excludes_infected_files(db):
    tenant = make_tenant(db)
    _make_gallery_image(db, tenant.id, scan_status="infected")
    db.commit()

    stats = service.file_stats(db, tenant.id)

    assert stats.photo_count == 0
    assert stats.document_count == 0
    assert stats.total_bytes == 0


def test_file_stats_scopes_to_the_given_tenant_only(db):
    tenant_a = make_tenant(db)
    tenant_b = make_tenant(db)
    _make_gallery_image(db, tenant_a.id)
    _make_gallery_image(db, tenant_b.id)
    _make_gallery_image(db, tenant_b.id)
    db.commit()

    stats_a = service.file_stats(db, tenant_a.id)

    assert stats_a.photo_count == 1


def test_file_stats_route_requires_writer_role(db):
    tenant = make_tenant(db)
    user = make_current_user(tenant.id, role="reader")

    with pytest.raises(HTTPException) as exc_info:
        files_routes.get_file_stats(db=db, user=user)
    assert exc_info.value.status_code == 403


def test_file_stats_route_returns_stats_for_writer_role(db):
    tenant = make_tenant(db)
    _make_gallery_image(db, tenant.id)
    db.commit()
    user = make_current_user(tenant.id, role="writer")

    result = files_routes.get_file_stats(db=db, user=user)

    assert result.photo_count == 1
