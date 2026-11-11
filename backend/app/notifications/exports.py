"""«Vereins-Datenexport fertig» (Benachrichtigungen Phase 3): Mail an die Person, die den Export
bestellt hat, sobald er bereitliegt oder fehlgeschlagen ist. Der Download selbst bleibt in der
App (Einstellungen > Datenschutz); die Mail enthält weder Datei noch Passwort."""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models import TenantDataExport
from app.notifications import publish

EXPORT_PATH = "/tenant-settings/privacy"


def on_export_finished(db: Session, job: TenantDataExport) -> None:
    """Ohne Commit; aufrufen, wenn der Status «done» oder «failed» gesetzt ist."""
    if job.requested_by is None or job.status not in ("done", "failed"):
        return
    publish(
        db, kind="export.ready" if job.status == "done" else "export.failed", tenant_id=job.tenant_id,
        recipient_ids=[job.requested_by], payload={"export_id": str(job.id)}, dedupe=str(job.id),
    )


def items_for(db: Session, notifications: list, recipient_id: int, **_) -> dict[int, dict]:
    items: dict[int, dict] = {}
    for notification in notifications:
        try:
            export_id = uuid.UUID(str(notification.payload.get("export_id")))
        except ValueError:
            continue
        job = db.get(TenantDataExport, export_id)
        if job is None or job.tenant_id != notification.tenant_id or job.requested_by != recipient_id:
            continue
        if notification.kind == "export.ready" and job.status != "done":
            continue
        items[notification.id] = {"kind": notification.kind, "filename": job.filename or ""}
    return items
