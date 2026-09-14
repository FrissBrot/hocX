"""Tests for FileService.analysis_progress - the tenant-wide summary behind the Fotos
page's "Foto-Analyse läuft - X von Y Bildern bewertet" progress bar and the "Analyse
läuft · N Bilder" pill. Route-level require_writer gating is tested by calling the route
function directly, same convention as test_files_overview.py."""

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app.api.routes import files as files_routes
from app.models.entities import GalleryImage, PhotoAnalysisJob, StoredFile
from app.services.file_service import FileService
from tests.factories import make_current_user, make_tenant

service = FileService()


def _make_gallery_image(db, tenant_id, *, mime_type="image/png", scan_status="clean", face_analyzed_at=None):
    stored_file = StoredFile(
        tenant_id=tenant_id, original_name="bild.png", mime_type=mime_type,
        storage_path="uploads/tenant-x/gallery/bild.png", scan_status=scan_status,
        face_analyzed_at=face_analyzed_at,
    )
    db.add(stored_file)
    db.flush()
    db.add(GalleryImage(tenant_id=tenant_id, stored_file_id=stored_file.id))
    db.flush()
    return stored_file


def test_analysis_progress_counts_analyzed_vs_pending(db):
    tenant = make_tenant(db)
    _make_gallery_image(db, tenant.id, face_analyzed_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    _make_gallery_image(db, tenant.id)
    _make_gallery_image(db, tenant.id)
    db.commit()

    progress = service.analysis_progress(db, tenant.id)

    assert progress.total_images == 3
    assert progress.analyzed_images == 1
    assert progress.pending_images == 2


def test_analysis_progress_excludes_infected_and_non_image_files(db):
    tenant = make_tenant(db)
    _make_gallery_image(db, tenant.id, scan_status="infected")
    _make_gallery_image(db, tenant.id, mime_type="application/pdf")
    db.commit()

    progress = service.analysis_progress(db, tenant.id)

    assert progress.total_images == 0


def test_analysis_progress_scopes_to_the_given_tenant_only(db):
    tenant_a = make_tenant(db)
    tenant_b = make_tenant(db)
    _make_gallery_image(db, tenant_a.id)
    _make_gallery_image(db, tenant_b.id)
    _make_gallery_image(db, tenant_b.id)
    db.commit()

    progress_a = service.analysis_progress(db, tenant_a.id)

    assert progress_a.total_images == 1


def test_analysis_progress_reports_active_job_counts(db):
    tenant = make_tenant(db)
    stored_file = _make_gallery_image(db, tenant.id)
    db.commit()
    db.add(PhotoAnalysisJob(tenant_id=tenant.id, stored_file_ids=[stored_file.id, stored_file.id + 1], status="running"))
    db.commit()

    progress = service.analysis_progress(db, tenant.id)

    assert progress.active_jobs == 1
    assert progress.active_job_image_count == 2


def test_analysis_progress_route_requires_writer_role(db):
    tenant = make_tenant(db)
    user = make_current_user(tenant.id, role="reader")

    with pytest.raises(HTTPException) as exc_info:
        files_routes.get_analysis_progress(db=db, user=user)
    assert exc_info.value.status_code == 403


def test_analysis_progress_route_returns_summary_for_writer_role(db):
    tenant = make_tenant(db)
    _make_gallery_image(db, tenant.id)
    db.commit()
    user = make_current_user(tenant.id, role="writer")

    result = files_routes.get_analysis_progress(db=db, user=user)

    assert result.total_images == 1
    assert result.pending_images == 1
