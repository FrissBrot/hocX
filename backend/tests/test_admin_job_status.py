"""Tests für die Job-Übersicht (/admin/jobs): die SQL-Funktionen aus Migration 0105, die
Zustandsberechnung in AdminJobStatusService und die Admin-Routen."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.api.routes import admin as admin_routes
from app.core.admin_security import CurrentAdmin
from app.core.job_registry import JOB_DEFINITIONS, JOBS_BY_NAME
from app.models import SystemJobRun, SystemJobStatus
from app.services.admin_job_status_service import AdminJobStatusService

service = AdminJobStatusService()


def _admin() -> CurrentAdmin:
    return CurrentAdmin(
        admin_id=1, admin_public_id=uuid.uuid4(), email="admin@example.com", display_name="Test Admin", role="owner"
    )


def _record(db, job_name: str, status: str, *, finished_at: datetime | None = None, error: str | None = None, keep_history: bool = True) -> None:
    finished_at = finished_at or datetime.now(timezone.utc)
    db.execute(
        text("SELECT record_job_run(:name, :status, :started, :finished, :error, :keep)"),
        {"name": job_name, "status": status, "started": finished_at - timedelta(seconds=2), "finished": finished_at, "error": error, "keep": keep_history},
    )
    db.flush()


def _clear(db) -> None:
    # Die Test-DB wird von laufenden Loops anderer Tests (lifespan smoke) mitbenutzt - jeder
    # Test startet darum mit leeren Tabellen (innerhalb der zurückgerollten Transaktion).
    db.execute(text("DELETE FROM system_job_run"))
    db.execute(text("DELETE FROM system_job_status"))


def _item(overview, name):
    return next(item for item in overview.items if item.name == name)


def test_record_job_run_tracks_counts_failures_and_keeps_last_error(db):
    _clear(db)
    _record(db, "export_cleanup", "failure", error="OSError: disk full")
    _record(db, "export_cleanup", "failure", error="OSError: disk full")

    row = db.get(SystemJobStatus, "export_cleanup")
    db.refresh(row)
    assert (row.last_status, row.consecutive_failures, row.run_count, row.failure_count) == ("failure", 2, 2, 2)

    _record(db, "export_cleanup", "success")
    db.refresh(row)
    assert (row.last_status, row.consecutive_failures, row.run_count, row.failure_count) == ("success", 0, 3, 2)
    # Bleibt nach einem Erfolg sichtbar, damit ein sporadischer Fehler nicht verschwindet.
    assert row.last_error == "OSError: disk full"
    assert row.last_success_at is not None and row.last_failure_at is not None


def test_record_job_run_without_history_keeps_only_failures_and_first_success_after(db):
    _clear(db)
    for status in ("success", "success", "failure", "success", "success"):
        _record(db, "gallery_upload_ingest", status, keep_history=False)

    statuses = [run.status for run in db.scalars(select(SystemJobRun).where(SystemJobRun.job_name == "gallery_upload_ingest").order_by(SystemJobRun.id))]
    assert statuses == ["success", "failure", "success"]


@pytest.mark.parametrize("bad_name", ["", "Export", "a b", "x" * 101, "drop;table"])
def test_record_job_run_rejects_invalid_job_names(db, bad_name):
    with pytest.raises(DBAPIError):
        with db.begin_nested():
            _record(db, bad_name, "success")


def test_overview_lists_every_registered_job_even_without_any_run(db):
    _clear(db)
    overview = service.get_overview(db)

    assert [item.name for item in overview.items] == [job.name for job in JOB_DEFINITIONS]
    assert {item.state for item in overview.items} == {"never_run"}
    assert all(item.registered for item in overview.items)


def test_overview_states(db):
    _clear(db)
    now = datetime.now(timezone.utc)
    upload_rescan = JOBS_BY_NAME["upload_pipeline_rescan"]
    _record(db, "upload_pipeline_rescan", "success", finished_at=now - timedelta(seconds=upload_rescan.max_silence_seconds + 60))
    _record(db, "abgabebox_rescan", "success", finished_at=now)
    _record(db, "export_cleanup", "failure", finished_at=now, error="RuntimeError: kaputt")
    db.execute(text("SELECT record_job_heartbeat('photo_analysis_worker')"))
    db.execute(text("SELECT record_job_start('log_cleanup')"))

    overview = service.get_overview(db, now=now + timedelta(seconds=1))

    assert _item(overview, "upload_pipeline_rescan").state == "overdue"
    assert _item(overview, "abgabebox_rescan").state == "ok"
    assert _item(overview, "export_cleanup").state == "failing"
    # Worker ohne Auftrag, aber mit Heartbeat ist gesund.
    assert _item(overview, "photo_analysis_worker").state == "ok"
    assert _item(overview, "log_cleanup").state == "running"


def test_overview_shows_reporting_jobs_that_are_not_registered(db):
    _clear(db)
    _record(db, "offsite_sync", "success")

    item = _item(service.get_overview(db), "offsite_sync")

    assert item.registered is False
    assert item.kind is None
    assert item.state == "ok"


def test_job_routes_return_overview_and_runs(db):
    _clear(db)
    _record(db, "cycle_snapshot", "failure", error="ValueError: x")
    _record(db, "cycle_snapshot", "success")

    overview = admin_routes.get_job_status(db=db, current_admin=_admin())
    assert _item(overview, "cycle_snapshot").state == "ok"

    runs = admin_routes.list_job_runs(job_name="cycle_snapshot", limit=1, offset=0, db=db, current_admin=_admin())
    assert runs.total == 2
    assert [run.status for run in runs.items] == ["success"]


def test_cleanup_old_runs_deletes_only_runs_past_retention(db):
    _clear(db)
    _record(db, "log_cleanup", "success", finished_at=datetime.now(timezone.utc) - timedelta(days=40))
    _record(db, "log_cleanup", "success")

    assert service.cleanup_old_runs(db, retention_days=30) == {"deleted": 1}
    assert db.scalar(select(SystemJobRun.id).where(SystemJobRun.job_name == "log_cleanup")) is not None
