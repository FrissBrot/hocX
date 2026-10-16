"""Plattform-Admin: System -> Backups (/admin/backups).

Das Backend legt nur Aufträge an und liest den Zustand - ausgeführt wird alles vom
backup-worker. Mutierende Aktionen: Owner (require_admin_write), Rate-Limit, Audit-Log,
Idempotenzschlüssel. Restores zusätzlich mit Bestätigungsphrase und frischer TOTP-Bestätigung.
Kein Endpunkt nimmt Dateipfade, Archivpfade oder Borg-Befehle entgegen - Sicherungspunkte werden
nur über ihre ID aus der Datenbank adressiert."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.admin_security import CurrentAdmin, get_current_admin, require_admin_write
from app.core.db import get_db
from app.core.rate_limit import enforce_rate_limit
from app.models import BackupJob, BackupRestoreJob, BackupSet
from app.schemas.backup_admin import (
    BackupCreate,
    BackupJobDetailRead,
    BackupJobPage,
    BackupJobRead,
    BackupSetRead,
    BackupSettingsRead,
    BackupSettingsUpdate,
    BackupStatusRead,
    BackupTenantRead,
    RestoreCreate,
    RestoreJobRead,
    RestorePreviewRead,
    RestorePreviewRequest,
    VerifyCreate,
)
from app.services import backup_admin_service as svc
from app.services.admin_mfa_service import AdminMfaService
from app.services.audit_service import AuditService

router = APIRouter(dependencies=[Depends(get_current_admin)])
audit = AuditService()

_KINDS = ("backup", "verify", "restore_test", "retention")
_STATES = ("queued", "preparing", "running", "verifying", "completed", "partial", "failed", "cancelled", "interrupted")
_TRIGGERS = ("schedule", "manual", "pre_restore", "pre_deploy", "cli")


def _limit(admin: CurrentAdmin, scope: str, limit: int = 20) -> None:
    enforce_rate_limit(f"admin-backup:{scope}:{admin.admin_id}", limit=limit, period_seconds=60)


def _audit(db: Session, admin: CurrentAdmin, action: str, **details) -> None:
    audit.log(db, action=action, actor_email=admin.email, entity_type="backup",
              details={k: str(v) if isinstance(v, uuid.UUID) else v for k, v in details.items()})


def _error(exc: svc.BackupAdminError) -> HTTPException:
    code = status.HTTP_409_CONFLICT if exc.code not in ("confirmation_mismatch", "rescue_reason_missing", "name_missing") else status.HTTP_422_UNPROCESSABLE_CONTENT
    return HTTPException(status_code=code, detail=str(exc))


# --- Übersicht und Verlauf --------------------------------------------------------------------


@router.get("/backups/status", response_model=BackupStatusRead)
def backup_status(db: Session = Depends(get_db)) -> BackupStatusRead:
    return svc.status(db)


@router.get("/backups/settings", response_model=BackupSettingsRead)
def backup_settings(db: Session = Depends(get_db)) -> BackupSettingsRead:
    return svc.read_settings(db)


@router.put("/backups/settings", response_model=BackupSettingsRead)
def update_backup_settings(payload: BackupSettingsUpdate, admin: CurrentAdmin = Depends(require_admin_write), db: Session = Depends(get_db)) -> BackupSettingsRead:
    _limit(admin, "settings")
    result, changes = svc.update_settings(db, payload, actor_email=admin.email)
    if changes:
        _audit(db, admin, "backup.settings.update", changes=changes)
    return result


@router.get("/backups/sets", response_model=list[BackupSetRead])
def backup_sets(include_pruned: bool = False, limit: int = Query(200, ge=1, le=1000), db: Session = Depends(get_db)) -> list[BackupSetRead]:
    query = select(BackupSet)
    if not include_pruned:
        query = query.where(BackupSet.state.in_(("completed", "partial")))
    return [svc.set_read(row) for row in db.scalars(query.order_by(BackupSet.snapshot_at.desc()).limit(limit))]


@router.get("/backups/sets/{set_id}/tenants", response_model=list[BackupTenantRead])
def backup_set_tenants(set_id: uuid.UUID, db: Session = Depends(get_db)) -> list[BackupTenantRead]:
    backup_set = db.get(BackupSet, set_id)
    if backup_set is None:
        raise HTTPException(status_code=404, detail="Sicherungspunkt nicht gefunden")
    return [BackupTenantRead(**{k: t.get(k) for k in ("id", "public_id", "name", "users", "objects", "bytes")}) for t in backup_set.tenants or []]


@router.get("/backups", response_model=BackupJobPage)
def backup_jobs(
    kind: str | None = Query(None), state: str | None = Query(None), trigger: str | None = Query(None),
    offset: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=200), db: Session = Depends(get_db),
) -> BackupJobPage:
    if (kind and kind not in _KINDS) or (state and state not in _STATES) or (trigger and trigger not in _TRIGGERS):
        raise HTTPException(status_code=422, detail="Ungültiger Filter")
    return svc.list_jobs(db, kind=kind, state=state, trigger=trigger, offset=offset, limit=limit)


@router.post("/backups", response_model=BackupJobRead, status_code=status.HTTP_202_ACCEPTED)
def create_backup(payload: BackupCreate, admin: CurrentAdmin = Depends(require_admin_write), db: Session = Depends(get_db)) -> BackupJobRead:
    _limit(admin, "create", 10)
    options = {"protected": True, "protected_reason": payload.reason or "Manuell geschützt"} if payload.protected else {}
    try:
        job, created = svc.create_job(db, kind="backup", trigger="manual", actor_email=admin.email, idempotency_key=payload.idempotency_key,
                                      options=options)
    except svc.BackupAdminError as exc:
        raise _error(exc) from None
    if created:
        _audit(db, admin, "backup.create", job_id=job.id, protected=payload.protected)
    return svc.job_read(db, job)


@router.post("/backups/restore-test", response_model=BackupJobRead, status_code=status.HTTP_202_ACCEPTED)
def create_restore_test(payload: VerifyCreate, admin: CurrentAdmin = Depends(require_admin_write), db: Session = Depends(get_db)) -> BackupJobRead:
    _limit(admin, "restore-test", 5)
    try:
        job, created = svc.create_job(db, kind="restore_test", trigger="manual", actor_email=admin.email, idempotency_key=payload.idempotency_key,
                                      options={"objects": "all" if payload.deep else "sample"})
    except svc.BackupAdminError as exc:
        raise _error(exc) from None
    if created:
        _audit(db, admin, "backup.restore_test.create", job_id=job.id, deep=payload.deep)
    return svc.job_read(db, job)


@router.get("/backups/{job_id}", response_model=BackupJobDetailRead)
def backup_job(job_id: uuid.UUID, db: Session = Depends(get_db)) -> BackupJobDetailRead:
    job = db.get(BackupJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Auftrag nicht gefunden")
    return svc.job_detail(db, job)


@router.post("/backups/{job_id}/verify", response_model=BackupJobRead, status_code=status.HTTP_202_ACCEPTED)
def verify_backup(job_id: uuid.UUID, payload: VerifyCreate, admin: CurrentAdmin = Depends(require_admin_write), db: Session = Depends(get_db)) -> BackupJobRead:
    _limit(admin, "verify", 5)
    job = db.get(BackupJob, job_id)
    if job is None or job.backup_set_id is None:
        raise HTTPException(status_code=404, detail="Kein Sicherungspunkt zu diesem Auftrag")
    try:
        verify, created = svc.create_job(db, kind="verify", trigger="manual", actor_email=admin.email, idempotency_key=payload.idempotency_key,
                                         options={"backup_set_id": str(job.backup_set_id), "deep": payload.deep})
    except svc.BackupAdminError as exc:
        raise _error(exc) from None
    if created:
        _audit(db, admin, "backup.verify.create", job_id=verify.id, backup_set_id=job.backup_set_id, deep=payload.deep)
    return svc.job_read(db, verify)


@router.post("/backups/{job_id}/cancel", response_model=BackupJobRead)
def cancel_backup(job_id: uuid.UUID, admin: CurrentAdmin = Depends(require_admin_write), db: Session = Depends(get_db)) -> BackupJobRead:
    _limit(admin, "cancel")
    job = db.get(BackupJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Auftrag nicht gefunden")
    try:
        svc.cancel_job(db, job, actor_email=admin.email)
    except svc.BackupAdminError as exc:
        raise _error(exc) from None
    _audit(db, admin, "backup.cancel", job_id=job.id)
    return svc.job_read(db, job)


# --- Restore ----------------------------------------------------------------------------------


@router.get("/restores", response_model=list[RestoreJobRead])
def restore_jobs(limit: int = Query(25, ge=1, le=200), db: Session = Depends(get_db)) -> list[RestoreJobRead]:
    rows = db.scalars(select(BackupRestoreJob).order_by(BackupRestoreJob.created_at.desc()).limit(limit)).all()
    return [svc.restore_read(db, row, with_events=False) for row in rows]


@router.post("/restores/preview", response_model=RestorePreviewRead)
def restore_preview(payload: RestorePreviewRequest, admin: CurrentAdmin = Depends(require_admin_write), db: Session = Depends(get_db)) -> RestorePreviewRead:
    _limit(admin, "preview", 30)
    try:
        return svc.preview(db, payload)
    except svc.BackupAdminError as exc:
        raise _error(exc) from None


@router.post("/restores", response_model=RestoreJobRead, status_code=status.HTTP_202_ACCEPTED)
def create_restore(payload: RestoreCreate, admin: CurrentAdmin = Depends(require_admin_write), db: Session = Depends(get_db)) -> RestoreJobRead:
    _limit(admin, "restore", 5)
    # Wiederholung derselben Anfrage (z. B. nach Netzwerkfehler): laufenden Auftrag zurückgeben,
    # es wird nichts Neues ausgelöst - der TOTP-Code ist dann bereits verbraucht.
    existing = svc.find_existing_restore(db, request=payload, actor_email=admin.email)
    if existing is not None:
        return svc.restore_read(db, existing)
    try:
        # Fachliche Prüfung (Blocker, Bestätigungsphrase) VOR dem TOTP: ein Tippfehler verbraucht keinen Code.
        plan = svc.validate_restore(db, payload)
        # Frische MFA-Bestätigung - unabhängig davon, wie lange die Sitzung schon besteht.
        AdminMfaService().verify_step_up_totp(db, admin_id=admin.admin_id, code=payload.totp_code, purpose="backup-restore")
        job, created = svc.create_restore(db, request=payload, actor_email=admin.email, plan=plan)
    except svc.BackupAdminError as exc:
        _audit(db, admin, "backup.restore.rejected", reason=exc.code, kind=payload.kind, backup_set_id=payload.backup_set_id)
        raise _error(exc) from None
    if created:
        _audit(db, admin, "backup.restore.create", restore_job_id=job.id, kind=job.kind, backup_set_id=job.backup_set_id,
               archive=job.archive_name, options=svc._sanitize_options(job.options))
    return svc.restore_read(db, job)


@router.get("/restores/{restore_id}", response_model=RestoreJobRead)
def restore_job(restore_id: uuid.UUID, db: Session = Depends(get_db)) -> RestoreJobRead:
    job = db.get(BackupRestoreJob, restore_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Wiederherstellung nicht gefunden")
    return svc.restore_read(db, job)


@router.post("/restores/{restore_id}/cancel", response_model=RestoreJobRead)
def cancel_restore(restore_id: uuid.UUID, admin: CurrentAdmin = Depends(require_admin_write), db: Session = Depends(get_db)) -> RestoreJobRead:
    _limit(admin, "cancel")
    job = db.get(BackupRestoreJob, restore_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Wiederherstellung nicht gefunden")
    try:
        svc.cancel_restore(db, job, actor_email=admin.email)
    except svc.BackupAdminError as exc:
        raise _error(exc) from None
    _audit(db, admin, "backup.restore.cancel", restore_job_id=job.id)
    return svc.restore_read(db, job)
