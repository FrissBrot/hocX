"""Vereinsexport (Mandanten-Einstellungen → Datenschutz, Datenschutz-Audit D2 / Paket 6).

Nur Mandanten-Admins mit bestätigter MFA in dieser Sitzung: das Archiv enthält alle Daten des
Vereins. Bestellen per POST (Passwort im Body), bauen im Job tenant_data_export, abholen 7 Tage lang.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db, release_for_stream
from app.core.rate_limit import enforce_rate_limit
from app.core.permissions import P
from app.core.security import CurrentUser, get_current_user, require_permission
from app.core.storage import MAIN, object_response
from app.models import TenantDataExport
from app.services.audit_service import AuditService
from app.services.data_export import tenant as tenant_export

router = APIRouter()


class TenantDataExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: str = Field(min_length=12, max_length=200)
    include_files: bool = True


class TenantDataExportRead(BaseModel):
    id: uuid.UUID
    status: Literal["queued", "running", "done", "failed", "expired"]
    include_files: bool
    created_at: datetime
    finished_at: datetime | None = None
    expires_at: datetime | None = None
    size_bytes: int | None = None
    missing_files: int = 0


def _read(job: TenantDataExport) -> TenantDataExportRead:
    missing = 0
    if job.status == "done" and job.error and job.error.startswith("missing:"):
        missing = int(job.error.split(":", 1)[1] or 0)
    return TenantDataExportRead(
        id=job.id, status=job.status, include_files=job.include_files, created_at=job.created_at,
        finished_at=job.finished_at, expires_at=job.expires_at, size_bytes=job.size_bytes, missing_files=missing,
    )


def _require_export_admin(user: CurrentUser) -> None:
    require_permission(user, P.DATA_EXPORT)
    if not user.mfa_verified:
        raise HTTPException(status_code=403, detail="Für den Vereinsexport ist eine Anmeldung mit Zwei-Faktor-Bestätigung nötig")


@router.get("/tenant-data-exports", response_model=list[TenantDataExportRead])
def list_tenant_data_exports(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_permission(user, P.DATA_EXPORT)
    return [_read(job) for job in tenant_export.list_exports(db, user.current_tenant_id)]


@router.post("/tenant-data-exports", response_model=TenantDataExportRead, status_code=202)
def create_tenant_data_export(payload: TenantDataExportRequest, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    _require_export_admin(user)
    enforce_rate_limit(f"tenant-data-export:{user.current_tenant_id}", limit=5, period_seconds=24 * 3600)
    try:
        job = tenant_export.request_export(
            db, tenant_id=user.current_tenant_id, user_id=user.user_id, password=payload.password,
            include_files=payload.include_files, language=user.preferred_language,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except tenant_export.ExportInProgress as exc:
        raise HTTPException(status_code=409, detail="Es läuft bereits ein Vereinsexport") from exc
    AuditService().log(
        db, action="tenant.data_export_requested", actor=user, entity_type="tenant", entity_id=user.current_tenant_id,
        details={"include_files": payload.include_files},
    )
    db.commit()
    db.refresh(job)
    return _read(job)


@router.get("/tenant-data-exports/{export_id}/download")
def download_tenant_data_export(export_id: uuid.UUID, request: Request, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    _require_export_admin(user)
    job = db.scalar(select(TenantDataExport).where(TenantDataExport.id == export_id, TenantDataExport.tenant_id == user.current_tenant_id))
    if job is None or job.status != "done" or not job.object_key:
        raise HTTPException(status_code=404, detail="Export nicht gefunden")
    AuditService().log(db, action="tenant.data_export_downloaded", actor=user, entity_type="tenant", entity_id=user.current_tenant_id)
    db.commit()
    return release_for_stream(db, object_response(request, MAIN, job.object_key, media_type="application/zip", filename=job.filename, attachment=True))
