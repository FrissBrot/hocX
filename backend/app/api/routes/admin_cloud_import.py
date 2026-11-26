"""Plattform-Admin: laufende Datei-Importe aller Mandanten und Kennzahlen (Plan §12.3).

Nur Zähler, Status und Mandantenname - keine Dateinamen, Pfade, Konten oder Tokens. Notfall-Abbruch
eines Imports (z. B. Anbieter sperrt die App, Worker überlastet) mit Audit-Eintrag.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.admin_security import CurrentAdmin, get_current_admin, require_admin_owner, require_admin_write
from app.core.admin_step_up import require_step_up
from app.core.db import get_db
from app.models.entities import Tenant
from app.models.import_entities import IMPORT_JOB_ACTIVE_STATUSES, ImportJob
from app.services.audit_service import AuditService
from app.services.cloud_import import jobs

router = APIRouter(dependencies=[Depends(get_current_admin)])

METRIC_DAYS = 30
ACTIVE_LIMIT = 200


class AdminImportRead(BaseModel):
    id: uuid.UUID
    tenant_name: str
    source: str
    status: str
    total_items: int
    total_bytes: int
    counts: dict[str, int]
    error: str | None
    created_at: datetime
    started_at: datetime | None
    last_progress_at: datetime | None
    not_before: datetime | None


class AdminImportMetricRead(BaseModel):
    day: str
    source: str
    jobs: int
    failed_jobs: int
    imported: int
    bytes: int
    failed_items: int


class AdminImportOverview(BaseModel):
    active: list[AdminImportRead]
    metrics: list[AdminImportMetricRead]
    days: int


_METRICS_SQL = text(
    """
    SELECT to_char((j.finished_at AT TIME ZONE 'Europe/Zurich')::date, 'YYYY-MM-DD') AS day, j.source,
           count(DISTINCT j.id) AS jobs,
           count(DISTINCT j.id) FILTER (WHERE j.status = 'failed') AS failed_jobs,
           count(i.id) FILTER (WHERE i.status = 'imported') AS imported,
           coalesce(sum(i.size_bytes) FILTER (WHERE i.status = 'imported'), 0) AS bytes,
           count(i.id) FILTER (WHERE i.status = 'failed') AS failed_items
    FROM import_job j
    LEFT JOIN import_item i ON i.job_id = j.id AND i.tenant_id = j.tenant_id
    WHERE j.status IN ('done', 'failed') AND j.finished_at >= now() - make_interval(days => :days)
    GROUP BY 1, 2
    ORDER BY 1 DESC, 2
    """
)


@router.get("/cloud-imports", response_model=AdminImportOverview)
def get_cloud_imports(db: Session = Depends(get_db), _admin: CurrentAdmin = Depends(require_admin_owner)):
    rows = db.execute(
        select(ImportJob, Tenant.name)
        .join(Tenant, Tenant.id == ImportJob.tenant_id)
        .where(ImportJob.status.in_(IMPORT_JOB_ACTIVE_STATUSES))
        .order_by(ImportJob.created_at)
        .limit(ACTIVE_LIMIT)
    ).all()
    active = []
    for job, tenant_name in rows:
        by_status, _codes, _bytes = jobs.status_counts(db, job)
        active.append(AdminImportRead(
            id=job.id, tenant_name=tenant_name or "", source=job.source, status=job.status, total_items=job.total_items,
            total_bytes=job.total_bytes, counts=by_status, error=job.error, created_at=job.created_at, started_at=job.started_at,
            last_progress_at=job.last_progress_at, not_before=job.not_before,
        ))
    metrics = [AdminImportMetricRead(**dict(row._mapping)) for row in db.execute(_METRICS_SQL, {"days": METRIC_DAYS})]
    return AdminImportOverview(active=active, metrics=metrics, days=METRIC_DAYS)


# Passkey-Bestätigung je Abbruch (Security-Review 1.6, I4), gebunden an Methode, Pfad und Body
@router.post("/cloud-imports/{job_id}/cancel", response_model=AdminImportRead, dependencies=[Depends(require_step_up("cloud-import-cancel"))])
def cancel_cloud_import(job_id: uuid.UUID, db: Session = Depends(get_db), admin: CurrentAdmin = Depends(require_admin_write)):
    """Notfall-Abbruch: wie der Abbruch im Verein (bereits importierte Dateien bleiben, Tokens weg)."""
    row = db.execute(
        select(ImportJob, Tenant.name).join(Tenant, Tenant.id == ImportJob.tenant_id).where(ImportJob.id == job_id).with_for_update(of=ImportJob)
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="not_found")
    job, tenant_name = row
    try:
        jobs.cancel(db, job)
    except jobs.ImportFailure as exc:
        raise HTTPException(status_code=exc.status, detail=exc.code) from None
    AuditService().log(
        db, action="admin.cloud_import_cancelled", actor_email=admin.email, tenant_id=job.tenant_id, entity_type="import_job",
        details={"job_id": str(job.id), "source": job.source, "status": job.status}, commit=False,
    )
    db.commit()
    by_status, _codes, _bytes = jobs.status_counts(db, job)
    return AdminImportRead(
        id=job.id, tenant_name=tenant_name or "", source=job.source, status=job.status, total_items=job.total_items,
        total_bytes=job.total_bytes, counts=by_status, error=job.error, created_at=job.created_at, started_at=job.started_at,
        last_progress_at=job.last_progress_at, not_before=job.not_before,
    )
