"""Mails zum Datei-Import (Plan §9), nur an die Person, die den Import gestartet hat (Kategorie
«Datei-Import», verlangt files.import - dispatch prüft das vor dem Versand):

- ``cloud_import.needs_reauth``: Cloud-Anbieter verlangt eine neue Anmeldung.
- ``cloud_import.done`` / ``cloud_import.failed``: Import (jede Quelle, auch ZIP/Ordner) beendet bzw.
  unterbrochen - nur Zahlen, Grund als Code und der Link zum Bericht, nie Dateinamen."""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models.import_entities import ImportJob
from app.notifications import publish

IMPORT_PATH = "/files/import"


def on_needs_reauth(db: Session, job: ImportJob) -> None:
    """Ohne Commit; einmal je Unterbrechung (dedupe mit dem Zeitpunkt)."""
    if job.requested_by is None:
        return
    publish(
        db, kind="cloud_import.needs_reauth", tenant_id=job.tenant_id, recipient_ids=[job.requested_by],
        payload={"job_id": str(job.id), "provider": job.source},
        dedupe=f"{job.id}:{(job.reauth_since.isoformat() if job.reauth_since else '')}",
    )


def on_job_end(db: Session, job: ImportJob) -> None:
    """Ohne Commit; aufrufen, sobald ein gestarteter Import «done» oder «failed» ist. Nie gestartete
    (verworfene Entwürfe) und abgebrochene Aufträge bekommen keine Mail."""
    if job.requested_by is None or job.status not in ("done", "failed") or job.started_at is None and job.status == "done":
        return
    publish(
        db, kind=f"cloud_import.{job.status}", tenant_id=job.tenant_id, recipient_ids=[job.requested_by],
        payload={"job_id": str(job.id)}, dedupe=f"{job.id}:{job.status}:{(job.finished_at.isoformat() if job.finished_at else '')}",
    )


_EXPECTED_STATUS = {"cloud_import.needs_reauth": "needs_reauth", "cloud_import.done": "done", "cloud_import.failed": "failed"}


def items_for(db: Session, notifications: list, recipient_id: int, **_) -> dict[int, dict]:
    from app.services.cloud_import import jobs

    items: dict[int, dict] = {}
    for notification in notifications:
        try:
            job_id = uuid.UUID(str(notification.payload.get("job_id")))
        except ValueError:
            continue
        job = db.get(ImportJob, job_id)
        # Überholt, sobald sich der Zustand geändert hat (neu angemeldet, fortgesetzt, …)
        if (
            job is None or job.tenant_id != notification.tenant_id or job.requested_by != recipient_id
            or job.status != _EXPECTED_STATUS.get(notification.kind)
        ):
            continue
        item = {"kind": notification.kind, "provider": job.source, "job_id": str(job.id), "error": job.error}
        if notification.kind != "cloud_import.needs_reauth":
            by_status, _codes, _bytes = jobs.status_counts(db, job)
            item.update(
                imported=int(by_status.get("imported", 0)), duplicates=int(by_status.get("duplicate", 0)),
                failed=int(by_status.get("failed", 0)),
            )
        items[notification.id] = item
    return items
