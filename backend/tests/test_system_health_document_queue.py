"""Systemcheck document_queue (Release 1.2.0): Monitoring der Dokumentverarbeitung aus
feature/document-management - gestaute oder endgültig gescheiterte Aufträge des document-worker
werden wie die Bildanalyse-Warteschlange gemeldet (Systemstatus, ntfy)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select, update

from app.core.storage import MAIN, get_object_store
from app.models import StoredFile
from app.models.document_entities import DocumentJob
from app.services import document_service, system_alert_service, system_health_service
from tests.factories import make_protocol, make_template, make_tenant


def _document_with_job(db) -> DocumentJob:
    tenant = make_tenant(db, "Queue-Verein")
    protocol = make_protocol(db, tenant.id, make_template(db, tenant.id).id, protocol_number="Q-1", protocol_date=date(2026, 5, 1))
    key = f"exports/generated/queue-{protocol.id}.pdf"
    get_object_store().put_bytes(db, MAIN, key, b"%PDF-1.4 queue", content_type="application/pdf")
    stored = StoredFile(tenant_id=tenant.id, original_name="q.pdf", mime_type="application/pdf", storage_path=key)
    db.add(stored)
    db.flush()
    result = document_service.record_protocol_export(
        db, tenant_id=tenant.id, protocol_id=protocol.id, export_kind="protocol", display_name="q.pdf",
        stored_file=stored, fingerprint="1" * 64, label=None,
    )
    job = db.scalar(select(DocumentJob).where(DocumentJob.document_version_id == result.version.id).limit(1))
    assert job is not None
    return job


def test_stalled_document_queue_is_a_warning_with_a_message(db):
    job = _document_with_job(db)
    now = datetime.now(UTC)
    db.execute(update(DocumentJob).where(DocumentJob.id == job.id).values(status="queued", run_after=now - timedelta(hours=2)))
    db.flush()

    check = system_health_service._check_document_queue(db, now)

    assert check.key == "document_queue" and check.status == "warning"
    assert check.params["queued"] >= 1 and check.params["oldestMinutes"] >= 119
    assert "document-worker" in system_alert_service._check_message(check)
    assert "document_queue" in system_alert_service._CHECK_PROBLEM_TITLES_DE


def test_recently_failed_document_job_is_a_warning(db):
    job = _document_with_job(db)
    now = datetime.now(UTC)
    db.execute(update(DocumentJob).where(DocumentJob.id == job.id).values(status="failed", updated_at=now))
    db.flush()

    check = system_health_service._check_document_queue(db, now)

    assert check.status == "warning" and check.params["failed"] >= 1


def test_document_queue_is_part_of_the_collected_checks(db):
    keys = {check.key for check in system_health_service.collect_checks(db, datetime.now(UTC))}
    assert "document_queue" in keys
