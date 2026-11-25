"""«Datei-Import: neu anmelden» (Plan §9): Mail an die Person, die einen Import aus einem
Cloud-Dienst gestartet hat, wenn der Anbieter die Verbindung nicht mehr erneuert (Passwortwechsel,
Widerruf). Ohne Dateinamen, nur der Link in den Wizard."""
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


def items_for(db: Session, notifications: list, recipient_id: int, **_) -> dict[int, dict]:
    items: dict[int, dict] = {}
    for notification in notifications:
        try:
            job_id = uuid.UUID(str(notification.payload.get("job_id")))
        except ValueError:
            continue
        job = db.get(ImportJob, job_id)
        # Überholt, sobald die Person sich neu angemeldet oder den Import beendet hat
        if job is None or job.tenant_id != notification.tenant_id or job.requested_by != recipient_id or job.status != "needs_reauth":
            continue
        items[notification.id] = {"kind": notification.kind, "provider": job.source}
    return items
