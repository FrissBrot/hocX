"""Photo-culling Phase 3: FileService.create_analysis_job/get_analysis_job and the
POST/GET /files/analysis-jobs routes. The worker itself (which actually scores the
queued files) lives in a separate container/codebase - see photo-analysis-worker/tests -
these tests only cover the backend side of the job queue: a job is created "queued" with
the right file ids and stays that way until the (out-of-process) worker moves it along."""

import io

import pytest
from fastapi import HTTPException
from PIL import Image

from app.api.routes import files as files_routes
from app.schemas.files import PhotoAnalysisJobCreate
from app.services.file_service import MAX_ANALYSIS_JOB_IMAGES, FileService
from tests.factories import make_current_user, make_tenant


@pytest.fixture(autouse=True)
def _isolated_storage_root(monkeypatch, tmp_path):
    from app.core.config import settings

    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(settings, "upload_root", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "thumbnail_root", str(tmp_path / "thumbnails"))


def _png_bytes(color=(10, 20, 30)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (48, 48), color=color).save(buffer, format="PNG")
    return buffer.getvalue()


service = FileService()


def test_create_analysis_job_queues_every_matching_image(db):
    tenant = make_tenant(db)
    service.save_gallery_uploads(
        db, tenant_id=tenant.id, files=[("a.png", _png_bytes((10, 20, 30))), ("b.png", _png_bytes((200, 30, 40)))], tags=[], created_by=None
    )
    db.commit()

    job = service.create_analysis_job(db, tenant.id)

    assert job.status == "queued"
    assert len(job.stored_file_ids) == 2
    assert job.finished_at is None


def test_create_analysis_job_rejects_when_nothing_matches(db):
    tenant = make_tenant(db)

    with pytest.raises(HTTPException) as exc_info:
        service.create_analysis_job(db, tenant.id)

    assert exc_info.value.status_code == 400


def test_create_analysis_job_rejects_above_the_size_cap(db, monkeypatch):
    tenant = make_tenant(db)
    service.save_gallery_uploads(db, tenant_id=tenant.id, files=[("a.png", _png_bytes())], tags=[], created_by=None)
    db.commit()
    monkeypatch.setattr("app.services.file_service.MAX_ANALYSIS_JOB_IMAGES", 0)

    with pytest.raises(HTTPException) as exc_info:
        service.create_analysis_job(db, tenant.id)

    assert exc_info.value.status_code == 400
    assert "Zu viele Bilder" in exc_info.value.detail


def test_get_analysis_job_is_scoped_to_its_own_tenant(db):
    tenant_a = make_tenant(db)
    tenant_b = make_tenant(db)
    service.save_gallery_uploads(db, tenant_id=tenant_a.id, files=[("a.png", _png_bytes())], tags=[], created_by=None)
    db.commit()
    job = service.create_analysis_job(db, tenant_a.id)

    fetched = service.get_analysis_job(db, tenant_a.id, job.id)
    assert fetched.id == job.id

    with pytest.raises(HTTPException) as exc_info:
        service.get_analysis_job(db, tenant_b.id, job.id)
    assert exc_info.value.status_code == 404


def test_create_analysis_job_route_requires_an_active_tenant(db):
    user = make_current_user(tenant_id=1, role="writer")
    user.current_tenant_id = None

    with pytest.raises(HTTPException) as exc_info:
        files_routes.create_analysis_job(PhotoAnalysisJobCreate(), db=db, user=user)
    assert exc_info.value.status_code == 400


def test_create_analysis_job_route_returns_a_queued_job(db):
    tenant = make_tenant(db)
    service.save_gallery_uploads(db, tenant_id=tenant.id, files=[("a.png", _png_bytes())], tags=[], created_by=None)
    db.commit()
    user = make_current_user(tenant_id=tenant.id, role="writer")

    result = files_routes.create_analysis_job(PhotoAnalysisJobCreate(), db=db, user=user)

    assert result.status == "queued"
    assert result.image_count == 1

    fetched = files_routes.get_analysis_job(result.id, db=db, user=user)
    assert fetched.id == result.id
