"""Concurrency-Audit CONC-008: Galerie-Ingest reihum je Mandant statt globaler FIFO, und ein
grosser ZIP gibt seine Zeitscheibe ab, wenn andere Mandanten warten."""
from datetime import UTC, datetime, timedelta

import pytest

from app.models.entities import GalleryUploadJob
from app.services import file_service as module
from app.services.file_service import FileService
from tests.factories import make_tenant


def _job(db, tenant_id, *, status="queued", minutes_ago=0, started_minutes_ago=None):
    job = GalleryUploadJob(
        tenant_id=tenant_id, status=status, staged_paths=[], original_filenames=[], tags=[], reserved_bytes=0,
        created_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
        started_at=None if started_minutes_ago is None else datetime.now(UTC) - timedelta(minutes=started_minutes_ago),
    )
    db.add(job)
    db.flush()
    return job


def test_next_job_prefers_the_tenant_served_longest_ago(db):
    db.query(GalleryUploadJob).filter(GalleryUploadJob.status == "queued").update({"status": "done"})
    busy, quiet = make_tenant(db), make_tenant(db)
    _job(db, busy.id, status="done", minutes_ago=5, started_minutes_ago=1)  # gerade bedient
    busy_waiting = _job(db, busy.id, minutes_ago=30)                         # älter
    quiet_waiting = _job(db, quiet.id, minutes_ago=2)                        # jünger, aber nie bedient
    assert FileService()._next_fair_gallery_job(db).id == quiet_waiting.id
    quiet_waiting.status = "done"
    db.flush()
    assert FileService()._next_fair_gallery_job(db).id == busy_waiting.id


def test_yielded_job_goes_behind_tenants_served_earlier(db):
    """Security-Review 10b: ein Job, der abgegeben hat (wieder "queued", started_at gesetzt),
    darf nicht sofort wieder drankommen - weder vor einem nie bedienten Mandanten noch vor einem,
    der zuletzt früher bedient wurde."""
    db.query(GalleryUploadJob).filter(GalleryUploadJob.status == "queued").update({"status": "done"})
    big, other, fresh = make_tenant(db), make_tenant(db), make_tenant(db)
    yielded = _job(db, big.id, minutes_ago=60, started_minutes_ago=2)   # einziger Job, hat abgegeben
    _job(db, other.id, status="done", minutes_ago=90, started_minutes_ago=30)
    other_waiting = _job(db, other.id, minutes_ago=1)
    assert FileService()._next_fair_gallery_job(db).id == other_waiting.id
    fresh_waiting = _job(db, fresh.id, minutes_ago=0)
    assert FileService()._next_fair_gallery_job(db).id == fresh_waiting.id
    fresh_waiting.status = other_waiting.status = "done"
    db.flush()
    assert FileService()._next_fair_gallery_job(db).id == yielded.id


def test_large_ingest_yields_only_when_others_wait(db, monkeypatch):
    db.query(GalleryUploadJob).filter(GalleryUploadJob.status == "queued").update({"status": "done"})
    tenant, other = make_tenant(db), make_tenant(db)
    running = _job(db, tenant.id, status="running")
    service = FileService()
    service._ingest_slice_deadline = 0  # Zeitscheibe abgelaufen
    service._yield_if_others_wait(db, running)  # niemand wartet: weiter
    _job(db, other.id)
    with pytest.raises(module._IngestYield):
        service._yield_if_others_wait(db, running)
