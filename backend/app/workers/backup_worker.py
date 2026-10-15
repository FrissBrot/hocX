"""Backup-Worker (eigener Container "backup-worker", gleiches Image wie das Backend).

    python -m app.workers.backup_worker

Einziger Prozess mit Zugang zum Borg-Repository (SSH-Schlüssel, Passphrase als Docker-Secrets).
Das Backend legt nur Aufträge an (backup_job, backup_restore_job); dieser Worker
- plant Backups (Takt aus backup_settings, Default alle 6 Stunden), Integritätsprüfungen,
  Restore-Tests und die Retention,
- führt Aufträge mit Lease + Fencing-Token aus (siehe app/backup/jobs.py), höchstens einen
  zugleich (zusätzlich PostgreSQL-Advisory-Lock: Repository und Inhaltsindex haben genau einen
  Schreiber),
- setzt unterbrochene Aufträge nach einem Neustart fort bzw. räumt sie sicher ab,
- meldet Läufe an /admin/jobs (record_job_*) und Ergebnisse von Restores per ntfy. Probleme
  (überfällig, Repository nicht erreichbar, Prüfung fehlgeschlagen, Platz knapp) meldet das
  Systemmonitoring (system_health_service._check_backup*), nicht der Worker selbst - so gibt es
  pro Problem genau eine entprellte Benachrichtigung.
"""

from __future__ import annotations

import logging
import math
import os
import signal
import socket
import threading
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, OperationalError

from app.backup import jobs
from app.backup.borg import Borg, BorgError
from app.backup.config import BackupConfigError, load_config
from app.backup.pgtools import PgToolError
from app.backup.restore_core import RestoreError
from app.backup.run_backup import RunEnv, finish_cleanup, preflight_repository
from app.backup.status import settings_row, update_repository_status
from app.core.background_loops import RESERVED_LOCK_IDS
from app.core.config import settings
from app.core.db import SessionLocal, engine
from app.core.error_log import record_system_error
from app.core.job_runs import format_job_error, record_job_run
from app.core.objstore_client import StorageError, StorageUnavailable
from app.core.storage import get_object_store
from app.models import BackupJob, BackupRestoreJob, BackupSet
from app.services import ntfy_client
from app.services.notification_settings_service import NotificationSettingsService
from app.services.storage_profile_service import profile_config

_logger = logging.getLogger("hocx.backup_worker")

JOB_NAME = "backup_worker"
RUN_JOB_NAMES = {"backup": "backup_run", "verify": "backup_verify", "restore_test": "backup_restore_test", "retention": "backup_retention"}
POLL_SECONDS = float(os.environ.get("BACKUP_WORKER_POLL_SECONDS", "10"))
REPOSITORY_PROBE_INTERVAL = timedelta(minutes=30)
ADVISORY_LOCK_ID = RESERVED_LOCK_IDS["backup_worker_repository"]
_SCHEDULE_BASE = datetime(2000, 1, 1, tzinfo=UTC)


def build_env() -> RunEnv:
    config = load_config()
    return RunEnv(
        config=config,
        borg=Borg(config),
        engine=engine,
        database_url=settings.database_url,
        store=get_object_store(),
        profile_config=profile_config,
        app_version=os.environ.get("HOCX_VERSION") or "unbekannt",
    )


# --- Planung ----------------------------------------------------------------------------------


def schedule_slot(now: datetime, interval_hours: int, offset_minutes: int) -> datetime:
    """Letzter fälliger Planzeitpunkt (UTC): Raster ab 00:00 + Versatz im Abstand des Intervalls."""
    base = _SCHEDULE_BASE + timedelta(minutes=offset_minutes)
    interval = timedelta(hours=interval_hours)
    steps = math.floor((now - base) / interval)
    return base + steps * interval


def _enqueue(db, *, kind: str, trigger: str, key: str, options: dict[str, Any] | None = None) -> bool:
    if db.scalar(select(BackupJob.id).where(BackupJob.idempotency_key == key)) is not None:
        return False
    if db.scalar(select(BackupJob.id).where(BackupJob.kind == kind, BackupJob.state.in_(jobs.OPEN_JOB_STATES))) is not None:
        return False
    db.add(BackupJob(kind=kind, trigger=trigger, idempotency_key=key, options=options or {}))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return False
    return True


def schedule_tick(db, now: datetime) -> list[str]:
    row = settings_row(db)
    created: list[str] = []
    if not row.schedule_enabled:
        return created
    slot = schedule_slot(now, row.interval_hours, row.schedule_offset_minutes)
    if _enqueue(db, kind="backup", trigger="schedule", key=f"schedule:{slot.isoformat()}"):
        created.append("backup")
    has_set = db.scalar(select(BackupSet.id).where(BackupSet.state.in_(("completed", "partial"))).limit(1)) is not None
    if not has_set:
        return created
    last_verify = db.scalar(select(BackupJob.finished_at).where(BackupJob.kind == "verify", BackupJob.state == "completed")
                            .order_by(BackupJob.finished_at.desc()).limit(1))
    if last_verify is None or now - last_verify > timedelta(hours=row.verify_interval_hours):
        if _enqueue(db, kind="verify", trigger="schedule", key=f"verify:{now:%Y%m%d%H}"):
            created.append("verify")
    last_test = db.scalar(select(BackupJob.finished_at).where(BackupJob.kind == "restore_test", BackupJob.state == "completed")
                          .order_by(BackupJob.finished_at.desc()).limit(1))
    if last_test is None or now - last_test > timedelta(days=row.restore_test_interval_days):
        if _enqueue(db, kind="restore_test", trigger="schedule", key=f"restore_test:{now:%Y%m%d}"):
            created.append("restore_test")
    if _enqueue(db, kind="retention", trigger="schedule", key=f"retention:{now:%Y%m%d}"):
        created.append("retention")
    return created


# --- Benachrichtigung -------------------------------------------------------------------------


def notify(db, title: str, message: str, *, priority: int = 3, tags: list[str] | None = None) -> None:
    try:
        NotificationSettingsService().send(db, ntfy_client.NtfyMessage(title=title, message=message, priority=priority,
                                                                        tags=tags or [], click="/admin/backups"))
    except ntfy_client.NtfyError:
        # Ergebnis steht am Einstellungsdatensatz (last_send_error) und im Admin-Portal.
        _logger.warning("ntfy-Benachrichtigung fehlgeschlagen", exc_info=True)


def _instance() -> str:
    return f"hocX {settings.traefik_domain}" if settings.traefik_domain else "hocX"


def daily_summary(db, now: datetime) -> None:
    row = settings_row(db)
    if row.success_notification != "daily" or (row.last_daily_summary_at and now - row.last_daily_summary_at < timedelta(hours=23)):
        return
    if now.hour < 6:
        return
    since = now - timedelta(hours=24)
    sets = db.scalars(select(BackupSet).where(BackupSet.snapshot_at >= since, BackupSet.state.in_(("completed", "partial")))).all()
    failed = db.scalar(select(text("COUNT(*)")).select_from(BackupJob).where(BackupJob.kind == "backup", BackupJob.state == "failed",
                                                                             BackupJob.finished_at >= since)) or 0
    new_bytes = sum(s.new_object_bytes for s in sets)
    notify(db, f"{_instance()}: Backup-Zusammenfassung",
           f"{len(sets)} Sicherungen in 24 Stunden ({sum(1 for s in sets if s.state == 'partial')} teilweise), {failed} fehlgeschlagen, "
           f"{round(new_bytes / 1024 ** 2)} MiB neu übertragen.", priority=2, tags=["floppy_disk"])
    row.last_daily_summary_at = now
    db.commit()


# --- Ausführung -------------------------------------------------------------------------------


def _advisory_lock():
    conn = engine.connect()
    locked = conn.execute(text("SELECT pg_try_advisory_lock(:id)"), {"id": ADVISORY_LOCK_ID}).scalar()
    if not locked:
        conn.close()
        return None
    return conn


def _cleanup(env: RunEnv, db, ctx: jobs.JobCtx, job: Any) -> None:
    from app.backup import run_restore

    try:
        if ctx.model is BackupJob and job.kind == "backup":
            finish_cleanup(env, db, job.checkpoint or {})
        elif ctx.model is BackupRestoreJob and job.kind == "full":
            run_restore.recover_interrupted_cutover(env)
            run_restore.cleanup_failed_full_restore(env, db, job)
        elif ctx.model is BackupRestoreJob and job.kind == "tenant_copy":
            run_restore.cleanup_failed_tenant_copy(env, db, job)
    except Exception as exc:  # noqa: BLE001 - Aufräumfehler sichtbar machen, Auftrag bleibt beendet
        db.rollback()
        _logger.exception("Aufräumen nach Auftrag %s fehlgeschlagen", ctx.job_id)
        record_system_error(db, exc=exc)


def _dispatch(env: RunEnv, db, ctx: jobs.JobCtx, job: Any) -> str:
    from app.backup import run_backup, run_maintenance, run_restore

    if ctx.model is BackupRestoreJob:
        return run_restore.run_full_restore(env, db, ctx) if job.kind == "full" else run_restore.run_tenant_copy(env, db, ctx)
    match job.kind:
        case "backup":
            return run_backup.run(env, db, ctx)
        case "retention":
            return run_maintenance.run_retention(env, db, ctx)
        case "verify":
            return run_maintenance.run_verify(env, db, ctx)
        case "restore_test":
            return run_maintenance.run_restore_test(env, db, ctx)
    raise jobs.JobFailure("unknown_kind", f"Unbekannte Auftragsart {job.kind}")


def _classify(exc: BaseException) -> tuple[str, str, bool]:
    if isinstance(exc, jobs.JobFailure):
        return exc.code, str(exc), exc.transient
    if isinstance(exc, BorgError):
        return f"borg_{exc.code}", str(exc), exc.transient
    if isinstance(exc, StorageUnavailable):
        return "storage_unavailable", str(exc), True
    if isinstance(exc, StorageError):
        return "storage_error", str(exc), False
    if isinstance(exc, (RestoreError, PgToolError)):
        return exc.code, str(exc), False
    if isinstance(exc, BackupConfigError):
        return "configuration", str(exc), False
    return "unexpected", f"{type(exc).__name__}: {exc}", False


def run_job(env: RunEnv, ctx: jobs.JobCtx) -> None:
    lock = _advisory_lock()
    if lock is None:
        jobs.release(ctx)
        return
    heartbeat = threading.Thread(target=jobs.heartbeat_loop, args=(ctx, _heartbeat_job), daemon=True)
    heartbeat.start()
    started = datetime.now(UTC)
    db = SessionLocal()
    job = None
    final: str | None = None
    final_message: str | None = None
    try:
        job = jobs.load(db, ctx)
        if ctx.resumed:
            jobs.guarded(db, ctx, attempt=job.attempt + 1)
            jobs.event(db, ctx, "resumed", "Auftrag nach Unterbrechung (Neustart/Absturz) wieder aufgenommen", level="warning")
            db.commit()
            job = jobs.load(db, ctx)
            if job.attempt > jobs.MAX_ATTEMPTS:
                _cleanup(env, db, ctx, job)
                jobs.set_state(db, ctx, "interrupted", message="Zu oft unterbrochen", level="error", error_code="interrupted")
                final = "interrupted"
                return
        if job.cancel_requested:
            ctx.cancel.set()
            ctx.check()
        final = _dispatch(env, db, ctx, job)
    except jobs.JobWait as wait:
        db.rollback()
        jobs.wait_later(db, ctx, seconds=wait.seconds, reason=wait.reason)
    except jobs.LeaseLost:
        db.rollback()
        _logger.warning("Lease für Auftrag %s verloren", ctx.job_id)
    except jobs.JobCancelled:
        db.rollback()
        job = jobs.load(db, ctx)
        if ctx.model is BackupRestoreJob and job.state == "cutover":
            # Während des Tauschs gibt es keinen sicheren Abbruch - weiterlaufen lassen.
            jobs.guarded(db, ctx, cancel_requested=False)
            db.commit()
        else:
            _cleanup(env, db, ctx, job)
            jobs.set_state(db, ctx, "cancelled", message="Abgebrochen", level="warning")
            final = "cancelled"
    except Exception as exc:  # noqa: BLE001 - jeder Fehler wird klassifiziert und gemeldet
        db.rollback()
        code, message, transient = _classify(exc)
        if code == "unexpected":
            _logger.exception("Auftrag %s fehlgeschlagen", ctx.job_id)
            record_system_error(db, exc=exc)
        try:
            job = jobs.load(db, ctx)
            in_cutover = ctx.model is BackupRestoreJob and job.state == "cutover"
            if transient and job.attempt < jobs.MAX_ATTEMPTS and not in_cutover:
                jobs.guarded(db, ctx, attempt=job.attempt + 1)
                jobs.retry_later(db, ctx, seconds=jobs.backoff_seconds(job.attempt + 1), code=code, message=message)
            else:
                if not in_cutover:
                    _cleanup(env, db, ctx, job)
                jobs.set_state(db, ctx, "failed", message=message, level="error", error_code=code, error_message=message[:2000])
                final = "failed"
                final_message = message
        except jobs.LeaseLost:
            pass
    finally:
        ctx.stop.set()
        heartbeat.join(timeout=5)
        try:
            if final is None:
                pass
            elif ctx.model is BackupJob and job is not None:
                status = "success" if final == "completed" else "failure"
                error = None if final == "completed" else (final_message or f"Auftrag endete mit Zustand {final}")
                record_job_run(RUN_JOB_NAMES.get(job.kind, "backup_run"), status=status, started_at=started,
                               finished_at=datetime.now(UTC), error=error)
            _after_job(env, ctx, job, final)
        finally:
            db.close()
            try:
                lock.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": ADVISORY_LOCK_ID})
            except OperationalError:
                # Verbindung beendet (Datenbanktausch beim Voll-Restore) - der Lock endete mit ihr.
                pass
            finally:
                lock.close()
            try:
                jobs.release(ctx)
            except Exception:  # noqa: BLE001 - Lease läuft notfalls ab
                _logger.warning("Lease konnte nicht freigegeben werden", exc_info=True)


def _after_job(env: RunEnv, ctx: jobs.JobCtx, job: Any, final: str | None) -> None:
    if final is None or job is None:
        return
    with SessionLocal() as db:
        if ctx.model is BackupRestoreJob:
            labels = {"completed": "erfolgreich abgeschlossen", "failed": "fehlgeschlagen", "rolled_back": "zurückgerollt",
                      "cancelled": "abgebrochen", "interrupted": "abgebrochen (Unterbrechungen)"}
            kind = "Voll-Restore" if job.kind == "full" else "Mandanten-Restore"
            fresh = db.get(BackupRestoreJob, job.id)
            notify(db, f"{_instance()}: {kind} {labels.get(final, final)}",
                   f"Sicherungspunkt {job.archive_name}. {(fresh.error_message if fresh is not None and fresh.error_message else '')}".strip(),
                   priority=2 if final == "completed" else 5, tags=["white_check_mark" if final == "completed" else "rotating_light"])
            return
        if job.kind == "backup" and final in ("completed", "partial"):
            fresh = db.get(BackupJob, job.id)
            if fresh is not None and fresh.backup_set_id:
                _enqueue(db, kind="retention", trigger="schedule", key=f"retention:{fresh.backup_set_id}")
            if final == "completed" and settings_row(db).success_notification == "each":
                notify(db, f"{_instance()}: Backup erfolgreich", f"Sicherung {(fresh.result or {}).get('archive', '')} abgeschlossen.",
                       priority=2, tags=["floppy_disk"])


def _heartbeat_job() -> None:
    try:
        with engine.begin() as conn:
            conn.execute(text("SELECT record_job_heartbeat(:job)"), {"job": JOB_NAME})
    except Exception:
        _logger.warning("Job-Heartbeat fehlgeschlagen", exc_info=True)


def probe_repository(env: RunEnv, db) -> None:
    row = settings_row(db)
    checked = row.repository_checked_at
    if checked is not None and datetime.now(UTC) - checked < REPOSITORY_PROBE_INTERVAL:
        return
    try:
        preflight_repository(env, db)
    except Exception:  # noqa: BLE001 - Ergebnis steht im Repository-Status (Monitoring meldet es)
        db.rollback()
        _logger.warning("Repository nicht erreichbar", exc_info=True)


def run_once(env: RunEnv | None, owner: str, *, disabled_reason: str = "disabled") -> float:
    _heartbeat_job()
    with SessionLocal() as db:
        if env is None:
            update_repository_status(db, ok=False, error_code=disabled_reason, checked_at=datetime.now(UTC).isoformat())
            return 60.0
        now = datetime.now(UTC)
        schedule_tick(db, now)
        daily_summary(db, now)
    for model in (BackupJob, BackupRestoreJob):
        ctx = jobs.claim(engine, model, owner)
        if ctx is not None:
            run_job(env, ctx)
            return 1.0
    with SessionLocal() as db:
        probe_repository(env, db)
    return POLL_SECONDS


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    owner = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"
    stopping = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopping.set())
    signal.signal(signal.SIGINT, lambda *_: stopping.set())
    env: RunEnv | None = None
    disabled_reason = "disabled"
    try:
        config = load_config()
        if config.enabled:
            config.validate()
            env = build_env()
            from app.backup.run_restore import recover_interrupted_cutover

            for action in recover_interrupted_cutover(env):
                _logger.warning("Restore-Journal: %s", action)
        else:
            _logger.warning("BACKUP_ENABLED ist nicht gesetzt - der Worker plant und führt keine Backups aus")
    except BackupConfigError:
        _logger.exception("Backup-Konfiguration ungültig - Worker läuft ohne Backups weiter (Status im Admin-Portal)")
        env = None
        disabled_reason = "configuration"
    _logger.info("backup-worker %s gestartet", owner)
    while not stopping.is_set():
        try:
            delay = run_once(env, owner, disabled_reason=disabled_reason)
        except Exception as exc:  # DB weg o. ä.: protokollieren, weiter versuchen
            _logger.exception("backup-worker: Durchlauf fehlgeschlagen")
            try:
                with SessionLocal() as db:
                    record_system_error(db, exc=exc)
            except Exception:
                pass
            delay = 30
        stopping.wait(delay)


if __name__ == "__main__":
    main()
