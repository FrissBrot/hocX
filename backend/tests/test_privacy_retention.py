"""Datenschutz-Audit PRIV-011: Job-, Ereignis- und Verlaufstabellen haben Fristen."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text

from app.core.config import settings
from app.models.entities import GalleryUploadJob, PhotoAnalysisJob, ShareLink
from app.services import retention_service
from tests.factories import make_tenant

OLD = datetime.now(UTC) - timedelta(days=400)
RECENT = datetime.now(UTC) - timedelta(days=1)


def test_finished_upload_jobs_expire_but_running_ones_stay(db):
    tenant = make_tenant(db)
    old_done = GalleryUploadJob(tenant_id=tenant.id, status="done", reserved_bytes=0, staged_paths=[], original_filenames=[], created_at=OLD, finished_at=OLD)
    old_running = GalleryUploadJob(tenant_id=tenant.id, status="running", reserved_bytes=0, staged_paths=[], original_filenames=[], created_at=OLD)
    recent_done = GalleryUploadJob(tenant_id=tenant.id, status="done", reserved_bytes=0, staged_paths=[], original_filenames=[], created_at=RECENT, finished_at=RECENT)
    analysis = PhotoAnalysisJob(tenant_id=tenant.id, status="failed", stored_file_ids=[], created_at=OLD, finished_at=OLD)
    db.add_all([old_done, old_running, recent_done, analysis])
    db.flush()
    keep = {old_running.id, recent_done.id}
    analysis_id = analysis.id

    retention_service.cleanup(db)

    remaining = set(db.scalars(select(GalleryUploadJob.id).where(GalleryUploadJob.tenant_id == tenant.id)))
    assert remaining == keep
    assert db.scalar(select(PhotoAnalysisJob.id).where(PhotoAnalysisJob.id == analysis_id)) is None


def test_revoked_or_expired_share_links_expire_active_ones_stay(db):
    tenant = make_tenant(db)
    revoked = ShareLink(tenant_id=tenant.id, name="alt", token="t-" + "a" * 30, revoked_at=OLD)
    expired = ShareLink(tenant_id=tenant.id, name="abgelaufen", token="t-" + "b" * 30, expires_at=OLD)
    active = ShareLink(tenant_id=tenant.id, name="aktiv", token="t-" + "c" * 30)
    fresh_revoked = ShareLink(tenant_id=tenant.id, name="neu widerrufen", token="t-" + "d" * 30, revoked_at=RECENT)
    db.add_all([revoked, expired, active, fresh_revoked])
    db.flush()

    retention_service.cleanup(db)

    remaining = set(db.scalars(select(ShareLink.name).where(ShareLink.tenant_id == tenant.id)))
    assert remaining == {"aktiv", "neu widerrufen"}


def test_rule_with_zero_days_is_disabled(db, monkeypatch):
    monkeypatch.setattr(settings, "submission_upload_log_retention_days", 0)

    result = retention_service.cleanup(db)

    assert "submission_upload_log" not in result


def test_every_rule_runs_against_the_real_schema(db):
    result = retention_service.cleanup(db)

    assert set(result) == {rule.table for rule in retention_service.RULES}


def test_fine_duplicate_copy_is_gone(db):
    assert db.scalar(text("SELECT to_regclass('public.attendance_fine_merged_duplicate')")) is None
