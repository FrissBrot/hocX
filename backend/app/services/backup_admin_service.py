"""Backup-Verwaltung für das Plattform-Admin-Portal und das Systemmonitoring.

Das Backend führt selbst nichts aus: es legt Aufträge an (idempotent), liest den Zustand, den
der backup-worker meldet, und leitet daraus Status und Probleme ab. Dieselbe Bewertung
(evaluate) nutzt system_health_service für /admin/system und die ntfy-Alarme."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import (
    BackupEvent,
    BackupJob,
    BackupRestoreJob,
    BackupSet,
    BackupSettings,
    StorageMigration,
    StorageProfile,
    StorageState,
    SystemJobStatus,
    Tenant,
)
from app.schemas.backup_admin import (
    BackupEventRead,
    BackupJobDetailRead,
    BackupJobPage,
    BackupJobRead,
    BackupProblemRead,
    BackupSetRead,
    BackupSettingsRead,
    BackupSettingsUpdate,
    BackupStatusRead,
    BackupTenantRead,
    RepositoryStatusRead,
    RestoreJobRead,
    RestorePreviewRead,
    RestorePreviewRequest,
)

OPEN_JOB_STATES = ("queued", "preparing", "running", "verifying")
OPEN_RESTORE_STATES = ("queued", "preparing", "running", "verifying", "cutover")
TERMINAL_JOB_STATES = ("completed", "partial", "failed", "cancelled", "interrupted")
WORKER_JOB_NAME = "backup_worker"
WORKER_STALE = timedelta(minutes=5)
_SCHEDULE_BASE = datetime(2000, 1, 1, tzinfo=UTC)
# Fehlermeldungen von Borg/SSH/pg können Pfade oder Hostnamen enthalten - nie Secrets (die werden
# nie in Meldungen geschrieben), aber gekürzt, damit die Oberfläche lesbar bleibt.
_MESSAGE_LIMIT = 600


class BackupAdminError(ValueError):
    """Kuratierter, erwarteter Fehler (wird als 409/422 an die Oberfläche gegeben)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def settings_row(db: Session) -> BackupSettings:
    row = db.get(BackupSettings, 1)
    if row is None:
        row = BackupSettings(id=1)
        db.add(row)
        db.flush()
    return row


def backup_enabled() -> bool:
    import os

    return (os.environ.get("BACKUP_ENABLED") or "").strip().lower() in ("1", "true", "yes", "on")


# --- Darstellung ------------------------------------------------------------------------------


def set_read(row: BackupSet) -> BackupSetRead:
    return BackupSetRead(
        id=row.id, archive_name=row.archive_name, state=row.state, trigger=row.trigger, protected=row.protected,
        protected_reason=row.protected_reason, snapshot_at=row.snapshot_at, finished_at=row.finished_at, app_version=row.app_version,
        alembic_revision=row.alembic_revision, generation=row.generation, profile_name=row.profile_name,
        profile_provider=row.profile_provider, db_dump_bytes=row.db_dump_bytes, object_count=row.object_count,
        object_bytes=row.object_bytes, new_object_count=row.new_object_count, new_object_bytes=row.new_object_bytes,
        deduplicated_bytes=row.deduplicated_bytes, duration_seconds=row.duration_seconds, verify_state=row.verify_state,
        verified_at=row.verified_at, restore_test_state=row.restore_test_state, restore_tested_at=row.restore_tested_at,
        warnings=[{"code": w.get("code"), "count": w.get("count"), "items": (w.get("items") or [])[:20]} for w in (row.warnings or [])],
        tenant_count=len(row.tenants or []), reconstructed=row.reconstructed,
    )


def _worker_active(lease_expires_at: datetime | None) -> bool:
    return lease_expires_at is not None and lease_expires_at > datetime.now(UTC)


def _duration(started: datetime | None, finished: datetime | None) -> int | None:
    if started is None:
        return None
    return int(((finished or datetime.now(UTC)) - started).total_seconds())


def job_read(db: Session, job: BackupJob) -> BackupJobRead:
    backup_set = db.get(BackupSet, job.backup_set_id) if job.backup_set_id else None
    return BackupJobRead(
        id=job.id, kind=job.kind, trigger=job.trigger, state=job.state, requested_by_email=job.requested_by_email,
        created_at=job.created_at, started_at=job.started_at, finished_at=job.finished_at, heartbeat_at=job.heartbeat_at,
        worker_active=_worker_active(job.lease_expires_at) and job.lease_owner != "wait", attempt=job.attempt,
        cancel_requested=job.cancel_requested, progress=job.progress or {}, error_code=job.error_code,
        error_message=(job.error_message or "")[:_MESSAGE_LIMIT] or None, warning_count=job.warning_count,
        duration_seconds=_duration(job.started_at, job.finished_at) if job.state not in ("queued",) else None,
        backup_set=set_read(backup_set) if backup_set else None,
    )


def _events(db: Session, *, job_id: uuid.UUID | None = None, restore_job_id: uuid.UUID | None = None) -> list[BackupEventRead]:
    query = select(BackupEvent)
    query = query.where(BackupEvent.job_id == job_id) if job_id else query.where(BackupEvent.restore_job_id == restore_job_id)
    return [BackupEventRead(id=e.id, created_at=e.created_at, level=e.level, kind=e.kind, actor_email=e.actor_email,
                            message=(e.message or "")[:_MESSAGE_LIMIT] or None, details=e.details or {})
            for e in db.scalars(query.order_by(BackupEvent.id.desc()).limit(200))]


def job_detail(db: Session, job: BackupJob) -> BackupJobDetailRead:
    base = job_read(db, job)
    backup_set = db.get(BackupSet, job.backup_set_id) if job.backup_set_id else None
    tenants = [BackupTenantRead(**{k: t.get(k) for k in ("id", "public_id", "name", "users", "objects", "bytes")})
               for t in (backup_set.tenants if backup_set else [])]
    return BackupJobDetailRead(**base.model_dump(), result=job.result, events=_events(db, job_id=job.id), tenants=tenants)


def _sanitize_options(options: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in (options or {}).items() if k not in ("totp_code",)}


def restore_read(db: Session, job: BackupRestoreJob, *, with_events: bool = True) -> RestoreJobRead:
    return RestoreJobRead(
        id=job.id, kind=job.kind, state=job.state, archive_name=job.archive_name, backup_set_id=job.backup_set_id,
        options=_sanitize_options(job.options), plan=job.plan or {}, requested_by_email=job.requested_by_email,
        created_at=job.created_at, started_at=job.started_at, finished_at=job.finished_at, heartbeat_at=job.heartbeat_at,
        worker_active=_worker_active(job.lease_expires_at) and job.lease_owner != "wait", progress=job.progress or {},
        error_code=job.error_code, error_message=(job.error_message or "")[:_MESSAGE_LIMIT] or None, result=job.result,
        cancel_requested=job.cancel_requested, events=_events(db, restore_job_id=job.id) if with_events else [],
    )


def repository_read(row: BackupSettings) -> RepositoryStatusRead:
    data = dict(row.repository_status or {})
    allowed = RepositoryStatusRead.model_fields
    return RepositoryStatusRead(**{k: v for k, v in data.items() if k in allowed})


# --- Bewertung (Admin-Portal + Monitoring) ----------------------------------------------------


def next_backup_at(row: BackupSettings, now: datetime) -> datetime | None:
    if not row.schedule_enabled:
        return None
    base = _SCHEDULE_BASE + timedelta(minutes=row.schedule_offset_minutes)
    interval = timedelta(hours=row.interval_hours)
    steps = (now - base) // interval
    return base + (steps + 1) * interval


def evaluate(db: Session, now: datetime | None = None) -> tuple[str, list[BackupProblemRead]]:
    """Gesamtzustand und Probleme. Codes werden in admin.backups.problems.<code> übersetzt."""
    now = now or datetime.now(UTC)
    row = settings_row(db)
    repo = dict(row.repository_status or {})
    problems: list[BackupProblemRead] = []
    if not backup_enabled() or repo.get("error_code") == "disabled":
        severity = "warning" if settings.is_production else None
        if severity:
            problems.append(BackupProblemRead(code="disabled", severity="warning"))
        return ("disabled", problems)
    if repo.get("error_code") == "configuration":
        problems.append(BackupProblemRead(code="configuration", severity="critical"))
    elif repo.get("ok") is False:
        problems.append(BackupProblemRead(code="repository_unreachable" if repo.get("error_code") not in ("repository_id_mismatch", "repository_not_encrypted", "passphrase_wrong", "host_key_mismatch") else repo["error_code"],
                                          severity="critical", params={"errorCode": repo.get("error_code")}))
    used = repo.get("used_percent")
    if isinstance(used, (int, float)) and used >= 85:
        problems.append(BackupProblemRead(code="capacity_low", severity="critical" if used >= 95 else "warning", params={"usedPercent": used}))
    latest = db.scalars(select(BackupSet).where(BackupSet.state.in_(("completed", "partial"))).order_by(BackupSet.snapshot_at.desc()).limit(1)).first()
    free = repo.get("staging_free_bytes")
    if latest is not None and isinstance(free, int) and latest.db_dump_bytes and free < 2 * latest.db_dump_bytes:
        problems.append(BackupProblemRead(code="staging_low", severity="warning", params={"freeBytes": free}))
    interval = timedelta(hours=row.interval_hours)
    last_ok = db.scalars(select(BackupSet).where(BackupSet.state == "completed").order_by(BackupSet.snapshot_at.desc()).limit(1)).first()
    if not row.schedule_enabled:
        problems.append(BackupProblemRead(code="schedule_disabled", severity="warning"))
    else:
        if last_ok is None:
            first_job = db.scalar(select(func.min(BackupJob.created_at)).where(BackupJob.kind == "backup"))
            if first_job is not None and now - first_job > interval + timedelta(hours=1):
                problems.append(BackupProblemRead(code="never_succeeded", severity="critical"))
        else:
            age = now - last_ok.snapshot_at
            if age > interval * 2 + timedelta(hours=1):
                problems.append(BackupProblemRead(code="overdue", severity="critical", params={"hours": int(age.total_seconds() // 3600)}))
            elif age > interval + timedelta(minutes=90):
                problems.append(BackupProblemRead(code="overdue", severity="warning", params={"hours": int(age.total_seconds() // 3600)}))
    if latest is not None and latest.state == "partial":
        missing = next((w.get("count") for w in (latest.warnings or []) if w.get("code") == "missing_objects"), 0)
        problems.append(BackupProblemRead(code="partial", severity="warning", params={"missing": missing}))
    last_job = db.scalars(select(BackupJob).where(BackupJob.kind == "backup", BackupJob.state.in_(TERMINAL_JOB_STATES))
                          .order_by(BackupJob.finished_at.desc().nulls_last()).limit(1)).first()
    if last_job is not None and last_job.state in ("failed", "interrupted"):
        problems.append(BackupProblemRead(code="last_failed", severity="warning", params={"errorCode": last_job.error_code}))
    for kind, code in (("verify", "verify_failed"), ("restore_test", "restore_test_failed")):
        last = db.scalars(select(BackupJob).where(BackupJob.kind == kind, BackupJob.state.in_(TERMINAL_JOB_STATES))
                          .order_by(BackupJob.finished_at.desc().nulls_last()).limit(1)).first()
        if last is not None and last.state == "failed":
            problems.append(BackupProblemRead(code=code, severity="critical" if kind == "verify" else "warning", params={"errorCode": last.error_code}))
    if last_ok is not None:
        verified = db.scalar(select(func.max(BackupSet.verified_at)).where(BackupSet.verify_state == "verified"))
        if verified is None or now - verified > timedelta(hours=row.verify_interval_hours * 2):
            problems.append(BackupProblemRead(code="verify_overdue", severity="warning"))
        tested = db.scalar(select(func.max(BackupSet.restore_tested_at)).where(BackupSet.restore_test_state == "passed"))
        if tested is None or now - tested > timedelta(days=row.restore_test_interval_days * 2):
            problems.append(BackupProblemRead(code="restore_test_overdue", severity="warning"))
    overall = "critical" if any(p.severity == "critical" for p in problems) else ("warning" if problems else "ok")
    return overall, problems


def status(db: Session) -> BackupStatusRead:
    now = datetime.now(UTC)
    row = settings_row(db)
    overall, problems = evaluate(db, now)
    sets = select(BackupSet).where(BackupSet.state.in_(("completed", "partial")))
    last_success = db.scalars(select(BackupSet).where(BackupSet.state == "completed").order_by(BackupSet.snapshot_at.desc()).limit(1)).first()
    latest = db.scalars(sets.order_by(BackupSet.snapshot_at.desc()).limit(1)).first()
    last_failure = db.scalars(select(BackupJob).where(BackupJob.kind == "backup", BackupJob.state.in_(("failed", "interrupted")))
                              .order_by(BackupJob.finished_at.desc().nulls_last()).limit(1)).first()
    verified = db.scalars(select(BackupSet).where(BackupSet.verify_state == "verified").order_by(BackupSet.verified_at.desc()).limit(1)).first()
    tested = db.scalars(select(BackupSet).where(BackupSet.restore_test_state == "passed").order_by(BackupSet.restore_tested_at.desc()).limit(1)).first()
    current = db.scalars(select(BackupJob).where(BackupJob.state.in_(OPEN_JOB_STATES)).order_by(BackupJob.created_at).limit(1)).first()
    restore = db.scalars(select(BackupRestoreJob).where(BackupRestoreJob.state.in_(OPEN_RESTORE_STATES)).limit(1)).first()
    worker = db.get(SystemJobStatus, WORKER_JOB_NAME)
    heartbeat = None
    if worker is not None:
        heartbeat = max((v for v in (getattr(worker, "last_heartbeat_at", None), getattr(worker, "last_finished_at", None)) if v), default=None)
    return BackupStatusRead(
        enabled=backup_enabled(), overall=overall, problems=problems,
        last_success=set_read(last_success) if last_success else None,
        last_failure=job_read(db, last_failure) if last_failure else None,
        next_backup_at=next_backup_at(row, now) if backup_enabled() else None,
        restore_point_count=int(db.scalar(select(func.count()).select_from(sets.subquery())) or 0),
        protected_count=int(db.scalar(select(func.count()).select_from(BackupSet).where(BackupSet.protected, BackupSet.state.in_(("completed", "partial")))) or 0),
        latest_object_bytes=latest.object_bytes if latest else None, latest_db_bytes=latest.db_dump_bytes if latest else None,
        repository=repository_read(row), last_verified_at=verified.verified_at if verified else None,
        last_verified_archive=verified.archive_name if verified else None,
        last_restore_test_at=tested.restore_tested_at if tested else None, last_restore_test_archive=tested.archive_name if tested else None,
        current_job=job_read(db, current) if current else None, current_restore=restore_read(db, restore, with_events=False) if restore else None,
        worker_heartbeat_at=heartbeat, worker_alive=heartbeat is not None and now - heartbeat < WORKER_STALE,
    )


# --- Aufträge ---------------------------------------------------------------------------------


def list_jobs(db: Session, *, kind: str | None, state: str | None, trigger: str | None, offset: int, limit: int) -> BackupJobPage:
    query = select(BackupJob)
    if kind:
        query = query.where(BackupJob.kind == kind)
    if state:
        query = query.where(BackupJob.state == state)
    if trigger:
        query = query.where(BackupJob.trigger == trigger)
    total = int(db.scalar(select(func.count()).select_from(query.subquery())) or 0)
    rows = db.scalars(query.order_by(BackupJob.created_at.desc()).offset(offset).limit(limit)).all()
    return BackupJobPage(items=[job_read(db, job) for job in rows], total=total, offset=offset, limit=limit)


def _require_enabled() -> None:
    if not backup_enabled():
        raise BackupAdminError("disabled", "Das Backup-System ist nicht eingerichtet (BACKUP_ENABLED)")


def create_job(db: Session, *, kind: str, trigger: str, actor_email: str, idempotency_key: str | None,
               options: dict[str, Any] | None = None) -> tuple[BackupJob, bool]:
    """Legt einen Auftrag an oder liefert den bestehenden (gleicher Idempotenzschlüssel oder
    bereits offener Auftrag derselben Art). Rückgabe: (Auftrag, neu angelegt)."""
    _require_enabled()
    key = f"admin:{actor_email}:{idempotency_key}" if idempotency_key else None
    if key:
        existing = db.scalars(select(BackupJob).where(BackupJob.idempotency_key == key)).first()
        if existing is not None:
            return existing, False
    open_job = db.scalars(select(BackupJob).where(BackupJob.kind == kind, BackupJob.state.in_(OPEN_JOB_STATES))).first()
    if open_job is not None:
        return open_job, False
    job = BackupJob(kind=kind, trigger=trigger, idempotency_key=key, requested_by_email=actor_email, options=options or {})
    db.add(job)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.scalars(select(BackupJob).where(BackupJob.kind == kind, BackupJob.state.in_(OPEN_JOB_STATES))).first()
        if existing is None:
            raise
        return existing, False
    db.add(BackupEvent(job_id=job.id, kind="requested", actor_email=actor_email, message="Auftrag im Admin-Portal angelegt"))
    db.commit()
    return job, True


def cancel_job(db: Session, job: BackupJob, *, actor_email: str) -> BackupJob:
    if job.state not in OPEN_JOB_STATES:
        raise BackupAdminError("not_cancellable", "Der Auftrag ist bereits beendet")
    job.cancel_requested = True
    if job.state == "queued" and not _worker_active(job.lease_expires_at):
        job.state = "cancelled"
        job.finished_at = datetime.now(UTC)
    db.add(BackupEvent(job_id=job.id, kind="cancel_requested", actor_email=actor_email, message="Abbruch angefordert", level="warning"))
    db.commit()
    return job


def read_settings(db: Session) -> BackupSettingsRead:
    from app.services.notification_settings_service import NotificationSettingsService

    row = settings_row(db)
    notification = NotificationSettingsService().get_row(db)
    return BackupSettingsRead(
        schedule_enabled=row.schedule_enabled, interval_hours=row.interval_hours, schedule_offset_minutes=row.schedule_offset_minutes,
        keep_within_days=row.keep_within_days, keep_daily=row.keep_daily, keep_weekly=row.keep_weekly, keep_monthly=row.keep_monthly,
        verify_interval_hours=row.verify_interval_hours, verify_sample_objects=row.verify_sample_objects,
        restore_test_interval_days=row.restore_test_interval_days, success_notification=row.success_notification,  # type: ignore[arg-type]
        worker_config=row.worker_config or {}, repository=repository_read(row),
        ntfy_configured=bool(notification.ntfy_server_url and notification.ntfy_topic),
        updated_at=row.updated_at, updated_by_email=row.updated_by_email,
    )


def update_settings(db: Session, payload: BackupSettingsUpdate, *, actor_email: str) -> tuple[BackupSettingsRead, dict[str, Any]]:
    row = settings_row(db)
    changes: dict[str, Any] = {}
    for field, value in payload.model_dump().items():
        if getattr(row, field) != value:
            changes[field] = {"from": getattr(row, field), "to": value}
            setattr(row, field, value)
    row.updated_at = datetime.now(UTC)
    row.updated_by_email = actor_email
    db.commit()
    return read_settings(db), changes


# --- Restore ----------------------------------------------------------------------------------


def _restorable_set(db: Session, backup_set_id: uuid.UUID) -> BackupSet:
    backup_set = db.get(BackupSet, backup_set_id)
    if backup_set is None or backup_set.state not in ("completed", "partial"):
        raise BackupAdminError("backup_not_restorable", "Sicherungspunkt nicht gefunden oder nicht wiederherstellbar")
    return backup_set


def confirmation_phrase(kind: str, backup_set: BackupSet) -> str:
    short = backup_set.id.hex[:8]
    return f"WIEDERHERSTELLEN {short}" if kind == "full" else f"KOPIE {short}"


def preview(db: Session, request: RestorePreviewRequest) -> RestorePreviewRead:
    from app.backup.restore_core import schema_compatibility

    _require_enabled()
    backup_set = _restorable_set(db, request.backup_set_id)
    compat = schema_compatibility(backup_set.alembic_revision)
    blockers: list[str] = []
    risks: list[str] = []
    if compat["state"] in ("newer", "unknown"):
        blockers.append("schema_newer")
    if db.scalar(select(BackupRestoreJob.id).where(BackupRestoreJob.state.in_(OPEN_RESTORE_STATES)).limit(1)) is not None:
        blockers.append("restore_running")
    if backup_set.state == "partial":
        risks.append("partial_backup")
    if any(w.get("code") == "dangling_references" for w in backup_set.warnings or []):
        risks.append("dangling_references")
    if backup_set.verify_state != "verified":
        risks.append("not_verified")
    if compat["state"] == "upgrade":
        risks.append("schema_upgrade")
    tenant = None
    profile = None
    name_conflict = False
    if request.kind == "full":
        if db.scalar(select(StorageMigration.id).where(StorageMigration.state.notin_(("completed", "failed", "cancelled"))).limit(1)) is not None:
            blockers.append("storage_migration_open")
        state = db.get(StorageState, 1)
        profile = (db.scalars(select(StorageProfile).where(StorageProfile.public_id == request.target_profile_id)).first()
                   if request.target_profile_id else db.get(StorageProfile, state.active_profile_id))
        if profile is None or not profile.is_enabled or profile.provider == "filesystem":
            blockers.append("target_profile_invalid")
        risks += ["full_replaces_data", "maintenance_downtime", "sessions_reset"]
        steps = ["rescue_backup", "restore_database", "restore_objects", "verify", "maintenance", "swap", "smoke_test", "release"]
        estimated = backup_set.object_bytes + int(backup_set.db_dump_bytes or 0)
    else:
        entry = next((t for t in backup_set.tenants or [] if int(t.get("id", 0)) == request.source_tenant_id), None)
        if entry is None:
            raise BackupAdminError("tenant_not_in_backup", "Der Mandant ist in diesem Sicherungspunkt nicht enthalten")
        tenant = BackupTenantRead(**{k: entry.get(k) for k in ("id", "public_id", "name", "users", "objects", "bytes")})
        if not request.new_name or not request.new_name.strip():
            blockers.append("name_missing")
        else:
            name_conflict = db.scalar(select(Tenant.id).where(func.lower(Tenant.name) == request.new_name.strip().lower())) is not None
            if name_conflict:
                risks.append("name_exists")
        risks += ["copy_users_existing_skipped", "copy_no_partner_relations"]
        steps = ["restore_temp_database", "collect_tenant", "restore_files", "import_new_tenant", "verify"]
        estimated = int(tenant.bytes) + int(backup_set.db_dump_bytes or 0)
    return RestorePreviewRead(
        kind=request.kind, backup_set=set_read(backup_set), schema_state=compat["state"], schema_revision=compat.get("revision"),
        schema_head=compat.get("head"), target_profile_name=profile.name if profile else None,
        target_profile_provider=profile.provider if profile else None, tenant=tenant, new_name=(request.new_name or "").strip() or None,
        name_conflict=name_conflict, steps=steps, risks=risks, blockers=blockers,
        confirmation_phrase=confirmation_phrase(request.kind, backup_set), estimated_bytes=estimated,
    )


def _restore_idempotency_key(request: Any, actor_email: str) -> str | None:
    return f"admin:{actor_email}:{request.idempotency_key}" if request.idempotency_key else None


def find_existing_restore(db: Session, *, request: Any, actor_email: str) -> BackupRestoreJob | None:
    """Wiederholung derselben Anfrage (gleicher Idempotenzschlüssel desselben Admins): der schon
    angelegte Auftrag - es wird nichts Neues ausgelöst."""
    key = _restore_idempotency_key(request, actor_email)
    if not key:
        return None
    return db.scalars(select(BackupRestoreJob).where(BackupRestoreJob.idempotency_key == key)).first()


def validate_restore(db: Session, request: Any) -> RestorePreviewRead:
    """Alle fachlichen Prüfungen VOR der TOTP-Bestätigung (ein Tippfehler in der Phrase
    verbraucht so keinen TOTP-Code)."""
    plan = preview(db, request)
    if plan.blockers:
        raise BackupAdminError(plan.blockers[0], "Wiederherstellung derzeit nicht möglich")
    if request.confirmation.strip() != plan.confirmation_phrase:
        raise BackupAdminError("confirmation_mismatch", "Die Bestätigung stimmt nicht")
    if request.kind == "full" and request.skip_rescue_backup and not (request.skip_rescue_reason or "").strip():
        raise BackupAdminError("rescue_reason_missing", "Ohne Rettungspunkt ist eine Begründung erforderlich")
    if not getattr(request, "replay_erasures", True) and not (getattr(request, "replay_erasures_reason", None) or "").strip():
        raise BackupAdminError("erasure_reason_missing", "Ohne erneutes Anwenden der Löschungen ist eine Begründung erforderlich")
    return plan


def create_restore(db: Session, *, request: Any, actor_email: str, plan: RestorePreviewRead | None = None) -> tuple[BackupRestoreJob, bool]:
    """request: RestoreCreate (TOTP wurde von der Route bereits geprüft). plan: Ergebnis von
    validate_restore, sonst wird hier geprüft."""
    key = _restore_idempotency_key(request, actor_email)
    existing = find_existing_restore(db, request=request, actor_email=actor_email)
    if existing is not None:
        return existing, False
    plan = plan or validate_restore(db, request)
    backup_set = _restorable_set(db, request.backup_set_id)
    options: dict[str, Any] = {}
    if request.kind == "full":
        options = {"target_profile_id": str(request.target_profile_id) if request.target_profile_id else None,
                   "skip_rescue_backup": bool(request.skip_rescue_backup), "skip_rescue_reason": request.skip_rescue_reason}
    else:
        options = {"source_tenant_id": request.source_tenant_id, "new_name": request.new_name.strip()}
    options["replay_erasures"] = bool(getattr(request, "replay_erasures", True))
    options["replay_erasures_reason"] = getattr(request, "replay_erasures_reason", None)
    now = datetime.now(UTC)
    job = BackupRestoreJob(kind=request.kind, idempotency_key=key, backup_set_id=backup_set.id, archive_name=backup_set.archive_name,
                           options=options, plan=plan.model_dump(mode="json", exclude={"backup_set"}), requested_by_email=actor_email,
                           confirmed_at=now, mfa_verified_at=now)
    db.add(job)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise BackupAdminError("restore_running", "Es läuft bereits eine Wiederherstellung") from exc
    db.add(BackupEvent(restore_job_id=job.id, kind="requested", actor_email=actor_email,
                       message="Wiederherstellung bestätigt (frische TOTP-Bestätigung)", details={"kind": request.kind}))
    db.commit()
    return job, True


def cancel_restore(db: Session, job: BackupRestoreJob, *, actor_email: str) -> BackupRestoreJob:
    if job.state not in ("queued", "preparing", "running", "verifying"):
        raise BackupAdminError("not_cancellable", "In diesem Zustand ist kein Abbruch möglich")
    job.cancel_requested = True
    if job.state == "queued" and not _worker_active(job.lease_expires_at):
        job.state = "cancelled"
        job.finished_at = datetime.now(UTC)
    db.add(BackupEvent(restore_job_id=job.id, kind="cancel_requested", actor_email=actor_email, message="Abbruch angefordert", level="warning"))
    db.commit()
    return job
