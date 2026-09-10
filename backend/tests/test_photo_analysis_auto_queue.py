"""Automatic off-peak queuing for Phase 3 (face-quality) analysis:
main.py's window/load gates and FileService.create_pending_analysis_jobs."""

import io
from datetime import datetime, timezone

import pytest
from PIL import Image
from sqlalchemy import text

from app.core.config import settings
from app.main import _host_load_is_low, _photo_analysis_auto_queue_window_is_open
from app.models.entities import PhotoAnalysisJob
from app.services.file_service import FileService
from tests.factories import make_tenant


def _png_bytes(color=(10, 20, 30)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (48, 48), color=color).save(buffer, format="PNG")
    return buffer.getvalue()


service = FileService()


def _mark_clean(db, tenant_id: int) -> None:
    """Test uploads land as scan_status='pending' here - there's no ClamAV in this test
    environment, see app/scanner.py's fail-open-to-pending behavior when it's unreachable.
    create_pending_analysis_jobs deliberately only ever auto-queues 'clean' files (never
    one still awaiting AV clearance), so exercising it needs this forced past that gate."""
    db.execute(text("UPDATE stored_file SET scan_status = 'clean' WHERE tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    db.commit()


@pytest.fixture(autouse=True)
def _isolated_storage_root(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(settings, "upload_root", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "thumbnail_root", str(tmp_path / "thumbnails"))


class _FixedDatetime(datetime):
    fixed_hour = 0

    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 1, 1, cls.fixed_hour, 0, tzinfo=tz)


def _set_hour(monkeypatch, hour: int):
    _FixedDatetime.fixed_hour = hour
    monkeypatch.setattr("app.main.datetime", _FixedDatetime)


def test_window_is_open_for_a_plain_non_wrapping_range(monkeypatch):
    monkeypatch.setattr(settings, "photo_analysis_auto_queue_start_hour", 1)
    monkeypatch.setattr(settings, "photo_analysis_auto_queue_end_hour", 6)

    _set_hour(monkeypatch, 3)
    assert _photo_analysis_auto_queue_window_is_open() is True

    _set_hour(monkeypatch, 6)
    assert _photo_analysis_auto_queue_window_is_open() is False

    _set_hour(monkeypatch, 12)
    assert _photo_analysis_auto_queue_window_is_open() is False


def test_window_wraps_past_midnight_when_start_is_after_end(monkeypatch):
    monkeypatch.setattr(settings, "photo_analysis_auto_queue_start_hour", 22)
    monkeypatch.setattr(settings, "photo_analysis_auto_queue_end_hour", 5)

    _set_hour(monkeypatch, 23)
    assert _photo_analysis_auto_queue_window_is_open() is True

    _set_hour(monkeypatch, 2)
    assert _photo_analysis_auto_queue_window_is_open() is True

    _set_hour(monkeypatch, 12)
    assert _photo_analysis_auto_queue_window_is_open() is False


def test_host_load_is_low_compares_against_cpu_count_times_factor(monkeypatch):
    monkeypatch.setattr(settings, "photo_analysis_auto_queue_max_load_factor", 0.5)
    monkeypatch.setattr("os.cpu_count", lambda: 4)

    monkeypatch.setattr("os.getloadavg", lambda: (1.5, 1.0, 1.0))
    assert _host_load_is_low() is True

    monkeypatch.setattr("os.getloadavg", lambda: (2.5, 1.0, 1.0))
    assert _host_load_is_low() is False


def test_host_load_is_low_defaults_to_true_when_getloadavg_unavailable(monkeypatch):
    def _raise():
        raise OSError("not supported on this platform")

    monkeypatch.setattr("os.getloadavg", _raise)
    assert _host_load_is_low() is True


def test_create_pending_analysis_jobs_queues_one_job_per_tenant_with_unanalyzed_images(db):
    tenant_a = make_tenant(db)
    tenant_b = make_tenant(db)
    service.save_gallery_uploads(db, tenant_id=tenant_a.id, files=[("a.png", _png_bytes())], tags=[], created_by=None)
    service.save_gallery_uploads(db, tenant_id=tenant_b.id, files=[("b.png", _png_bytes())], tags=[], created_by=None)
    db.commit()
    _mark_clean(db, tenant_a.id)
    _mark_clean(db, tenant_b.id)

    created = service.create_pending_analysis_jobs(db)

    # >= rather than == : a seeded demo tenant with its own unanalyzed images may also
    # legitimately qualify, this only asserts the two tenants under test were found.
    created_by_tenant = {job.tenant_id: job for job in created}
    assert tenant_a.id in created_by_tenant
    assert tenant_b.id in created_by_tenant
    assert created_by_tenant[tenant_a.id].status == "queued"
    assert created_by_tenant[tenant_a.id].requested_by is None


def test_create_pending_analysis_jobs_skips_a_tenant_with_an_already_active_job(db):
    tenant = make_tenant(db)
    service.save_gallery_uploads(db, tenant_id=tenant.id, files=[("a.png", _png_bytes())], tags=[], created_by=None)
    db.commit()
    _mark_clean(db, tenant.id)
    service.create_analysis_job(db, tenant.id)  # first sweep queues it

    second_sweep = service.create_pending_analysis_jobs(db)

    assert tenant.id not in {job.tenant_id for job in second_sweep}
    assert db.query(PhotoAnalysisJob).filter_by(tenant_id=tenant.id).count() == 1


def test_create_pending_analysis_jobs_finds_nothing_once_everything_is_already_scored(db):
    tenant = make_tenant(db)
    items, _errors = service.save_gallery_uploads(db, tenant_id=tenant.id, files=[("a.png", _png_bytes())], tags=[], created_by=None)
    db.commit()
    _mark_clean(db, tenant.id)
    stored_file_id = service.stored_file_repository.get_by_public_id(db, items[0].id, tenant_id=tenant.id).id
    service.stored_file_repository.get(db, stored_file_id).face_quality_score = 42.0
    db.commit()

    created = service.create_pending_analysis_jobs(db)

    assert tenant.id not in {job.tenant_id for job in created}
