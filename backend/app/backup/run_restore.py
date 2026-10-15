"""Restore-Aufträge des Workers: Voll-Restore (kind=full) und Mandanten-Restore als Kopie
(kind=tenant_copy). Ablauf siehe docs-site/docs/technik/backup/restore.md.

Voll-Restore, Phasen (checkpoint["phase"]):
  rescue     Rettungspunkt des aktuellen Zustands (geschützter Backup-Auftrag), ausser bewusst
             abgewählt
  prepare    Repository, Metadaten, Schema-Kompatibilität, Zielprofil, neue Generation reservieren
  database   Dump in eine neue Datenbank hocx_restore_<id>
  objects    Objekte aus Borg in die neue Generation des Zielprofils
  verify     ggf. Alembic-Upgrade (erst nach erfolgreicher Wiederherstellung), Speicher auf die
             neue Generation umstellen, Referenzprüfung, Anwendungstest
  cutover    Wartung, Schreib-Fence, Backup-Tabellen übernehmen, Datenbanken tauschen
             (Umbenennen), Smoke-Test, Freigabe - scheitert der Smoke-Test, wird automatisch
             zurückgetauscht (rolled_back).
Die bisherige Datenbank bleibt als hocx_pre_restore_<zeit> erhalten, die bisherige Generation
unberührt. Ein lokales Journal (BACKUP_WORK_DIR/restore-journal) macht den Tausch
absturzsicher: recover_interrupted_cutover() stellt beim Start immer einen Zustand mit
erreichbarer Live-Datenbank her.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.backup import jobs
from app.backup.pgtools import PgTarget, PgTools, validate_db_name
from app.backup.repository import RepositoryView
from app.backup.restore_core import (
    PROFILE_COLUMNS,
    RestoreError,
    configure_restored_database,
    ensure_empty_generation,
    iter_manifest_slices,
    load_restore_point,
    purge_generation_objects,
    reference_report,
    restore_database,
    restore_objects,
    restored_keys_from_manifest,
    run_alembic_upgrade,
    schema_compatibility,
    write_contents_sink,
)
from app.backup.run_backup import RunEnv, preflight_repository
from app.backup.run_maintenance import smoke_test_database
from app.backup.tenant_recovery import (
    HistoricalTenantExport,
    RecoveryFileSource,
    prepare_copy_manifest,
    purge_staging,
    staging_key,
)
from app.models import BackupJob, BackupRestoreJob, StorageGeneration, StorageMigration, StorageProfile, StorageState

_logger = logging.getLogger("hocx.backup.restore_job")

BACKUP_TABLES = ("backup_settings", "backup_set", "backup_job", "backup_pool_archive", "backup_content", "backup_restore_job", "backup_event")
APP_ROLES = ("hocx_app", "hocx_abgabebox", "hocx_photo_worker")
CUTOVER_LOCK_TIMEOUT = "20s"


def _journal_dir(env: RunEnv) -> Path:
    path = env.config.work_dir / "restore-journal"
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def _write_journal(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    with tmp.open("rb") as handle:
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def _profile_values(profile: StorageProfile) -> dict[str, Any]:
    values = {column: getattr(profile, column) for column in PROFILE_COLUMNS}
    values["public_id"] = profile.public_id
    values["name"] = profile.name
    return values


# --- Voll-Restore -----------------------------------------------------------------------------


def _rescue(env: RunEnv, db: Session, ctx: jobs.JobCtx, job: BackupRestoreJob) -> None:
    options = job.options or {}
    checkpoint = job.checkpoint or {}
    if options.get("skip_rescue_backup"):
        jobs.event(db, ctx, "rescue_skipped", "Rettungspunkt bewusst übersprungen", level="warning",
                   reason=options.get("skip_rescue_reason"))
        jobs.checkpoint(db, ctx, phase="prepare")
        return
    rescue_id = checkpoint.get("rescue_job_id")
    if rescue_id:
        rescue = db.get(BackupJob, uuid.UUID(rescue_id), populate_existing=True)
        if rescue is None or rescue.state in ("failed", "cancelled", "interrupted"):
            raise jobs.JobFailure("rescue_backup_failed", "Der Rettungspunkt vor dem Restore konnte nicht erstellt werden - Restore abgebrochen")
        if rescue.state in ("completed", "partial"):
            jobs.event(db, ctx, "rescue_done", f"Rettungspunkt erstellt ({rescue.state})", backup_set_id=rescue.backup_set_id)
            jobs.checkpoint(db, ctx, phase="prepare", rescue_backup_set_id=str(rescue.backup_set_id))
            return
        raise jobs.JobWait(15, "rescue_backup_running")
    rescue = BackupJob(kind="backup", trigger="pre_restore", idempotency_key=f"pre_restore:{job.id}",
                       requested_by_email=job.requested_by_email,
                       options={"protected": True, "protected_reason": f"Rettungspunkt vor Restore {job.id}"})
    db.add(rescue)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        # Ein anderer Backup-Auftrag läuft gerade - danach den Rettungspunkt anlegen.
        raise jobs.JobWait(30, "backup_running") from exc
    jobs.checkpoint(db, ctx, rescue_job_id=str(rescue.id))
    jobs.event(db, ctx, "rescue_started", "Rettungspunkt des aktuellen Zustands wird erstellt", backup_job_id=rescue.id)
    db.commit()
    raise jobs.JobWait(10, "rescue_backup_running")


def _prepare(env: RunEnv, db: Session, ctx: jobs.JobCtx, job: BackupRestoreJob, view: RepositoryView) -> dict[str, Any]:
    metadata = load_restore_point(view, job.archive_name)
    compat = schema_compatibility(metadata.get("alembic_revision"))
    if compat["state"] in ("newer", "unknown"):
        raise jobs.JobFailure("schema_incompatible",
                              f"Das Backup stammt von einer neueren/unbekannten hocX-Version (Revision {compat['revision']}) - zuerst diese Version einspielen")
    open_migration = db.scalar(select(StorageMigration.id).where(StorageMigration.state.notin_(("completed", "failed", "cancelled"))).limit(1))
    if open_migration is not None:
        raise jobs.JobFailure("storage_migration_open", "Während einer Storage-Migration ist kein Restore möglich")
    options = job.options or {}
    state = db.get(StorageState, 1)
    profile_id = options.get("target_profile_id")
    profile = (db.scalars(select(StorageProfile).where(StorageProfile.public_id == uuid.UUID(profile_id))).first()
               if profile_id else db.get(StorageProfile, state.active_profile_id))
    if profile is None or not profile.is_enabled:
        raise jobs.JobFailure("target_profile_invalid", "Zielprofil nicht gefunden oder deaktiviert")
    if profile.provider == "filesystem":
        raise jobs.JobFailure("target_profile_invalid", "Ein Voll-Restore schreibt immer in eine neue Generation eines S3-Profils")
    live_max = int(db.scalar(select(func.max(StorageGeneration.generation))) or 0)
    generation = max(live_max, int((metadata.get("storage") or {}).get("generation") or 0)) + 1
    db.add(StorageGeneration(profile_id=profile.id, generation=generation, status="preparing"))
    db.commit()
    backend = env.store.make_backend(env.profile_config(profile, generation))
    ensure_empty_generation(backend)
    target = PgTarget.from_url(env.database_url)
    restore_db = f"hocx_restore_{ctx.job_id.hex[:12]}"
    values = {"phase": "database", "generation": generation, "profile_id": profile.id, "restore_db": restore_db,
              "live_db": target.database, "schema": compat, "object_count": metadata.get("object_count"),
              "missing_objects": int(metadata.get("missing_objects") or 0)}
    jobs.checkpoint(db, ctx, **values)
    jobs.event(db, ctx, "prepared", f"Ziel: Profil {profile.name}, neue Generation {generation}, Datenbank {restore_db}")
    db.commit()
    return values


def _database(env: RunEnv, db: Session, ctx: jobs.JobCtx, job: BackupRestoreJob, view: RepositoryView, cp: dict[str, Any]) -> None:
    metadata = load_restore_point(view, job.archive_name)
    target = PgTarget.from_url(env.database_url)
    with PgTools(target) as pg:
        if pg.database_exists(cp["restore_db"]):
            pg.drop_database(cp["restore_db"])  # unvollständiger Versuch eines früheren Laufs
        owner = pg.psql(f"SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = '{validate_db_name(cp['live_db'])}';", database="postgres")
        result = restore_database(view, job.archive_name, metadata, pg, cp["restore_db"], env.config.staging_dir / f"restore-{ctx.job_id.hex}",
                                  max_bytes=env.config.staging_max_bytes, jobs=env.config.pg_restore_jobs, owner=owner or None)
        pg.psql(f'GRANT CONNECT ON DATABASE "{cp["restore_db"]}" TO {", ".join(APP_ROLES)};', database="postgres")
    jobs.event(db, ctx, "database_restored", f"Datenbank {cp['restore_db']} wiederhergestellt", **result)
    jobs.checkpoint(db, ctx, phase="objects")


def _objects(env: RunEnv, db: Session, ctx: jobs.JobCtx, job: BackupRestoreJob, view: RepositoryView, cp: dict[str, Any]) -> None:
    metadata = load_restore_point(view, job.archive_name)
    profile = db.get(StorageProfile, cp["profile_id"])
    backend = env.store.make_backend(env.profile_config(profile, cp["generation"]))
    result = restore_objects(view, job.archive_name, metadata, backend, env.config.staging_dir / f"restore-{ctx.job_id.hex}",
                             should_stop=ctx.check, skip_existing=ctx.resumed,
                             progress=lambda values: jobs.progress(db, ctx, phase="objects", **values))
    if not result["ok"]:
        raise jobs.JobFailure("objects_incomplete", f"{result['missing_count']} Inhalte fehlen, {result['corrupt_count']} sind beschädigt - Restore abgebrochen")
    jobs.event(db, ctx, "objects_restored", f"{result['contents_restored']} Inhalte in Generation {cp['generation']} geschrieben", **result)
    jobs.checkpoint(db, ctx, phase="verify")


def _verify(env: RunEnv, db: Session, ctx: jobs.JobCtx, job: BackupRestoreJob, view: RepositoryView, cp: dict[str, Any]) -> None:
    metadata = load_restore_point(view, job.archive_name)
    target = PgTarget.from_url(env.database_url)
    restored_url = target.with_database(cp["restore_db"]).sqlalchemy_url()
    if cp["schema"]["state"] == "upgrade":
        jobs.progress(db, ctx, phase="alembic")
        run_alembic_upgrade(restored_url)
        jobs.event(db, ctx, "alembic_upgraded", f"Schema von {cp['schema']['revision']} auf {cp['schema']['head']} aktualisiert")
        db.commit()
    profile = db.get(StorageProfile, cp["profile_id"])
    configured = configure_restored_database(restored_url, profile=_profile_values(profile), generation=cp["generation"])
    jobs.progress(db, ctx, phase="references")
    report = reference_report(restored_url, restored_keys_from_manifest(view, job.archive_name, metadata, env.config.staging_dir / f"restore-{ctx.job_id.hex}"))
    if report["registry_without_object_count"] != cp.get("missing_objects", 0):
        raise jobs.JobFailure("reference_check_failed", f"{report['registry_without_object_count']} registrierte Objekte ohne wiederhergestellten Inhalt")
    smoke = smoke_test_database(restored_url)
    if not smoke["ok"]:
        raise jobs.JobFailure("smoke_test_failed", f"Anwendungstest gegen die wiederhergestellte Datenbank fehlgeschlagen: {smoke['problems'][:3]}")
    jobs.guarded(db, ctx, result={"configured": configured, "references": report, "smoke": smoke})
    jobs.event(db, ctx, "verified", f"Prüfung ok: {report['tenants']} Mandanten, {report['users']} Benutzer, "
               f"{report['missing_reference_count']} vorbestehende Referenzlücken", references=report["missing_reference_count"])
    jobs.checkpoint(db, ctx, phase="cutover")


def _insert_window(database_url: str, job_id: uuid.UUID) -> uuid.UUID:
    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with engine.begin() as conn:
            return conn.execute(text("""
                INSERT INTO maintenance_window (kind, block_scope, state, reason_code, affected_features, source_job_type, source_job_id,
                                                started_at, internal_note)
                VALUES ('full', 'all', 'active', 'backup_restore', '["all"]'::jsonb, 'backup_restore', :job, NOW(),
                        'Wiederherstellung aus dem Backup - Freigabe nach erfolgreichem Smoke-Test')
                RETURNING id
            """), {"job": str(job_id)}).scalar_one()
    finally:
        engine.dispose()


def _cutover(env: RunEnv, db: Session, ctx: jobs.JobCtx, job: BackupRestoreJob, cp: dict[str, Any]) -> str:
    from app.services import maintenance_service

    target = PgTarget.from_url(env.database_url)
    live, restored = cp["live_db"], cp["restore_db"]
    pre = cp.get("pre_restore_db") or f"hocx_pre_restore_{datetime.now(UTC):%Y%m%d%H%M%S}"
    journal_path = _journal_dir(env) / f"{ctx.job_id.hex}.json"
    journal = json.loads(journal_path.read_text()) if journal_path.exists() else {}
    if journal.get("step") == "renamed_restored":
        return _after_swap(env, ctx, job, cp, journal, journal_path)
    restored_url = target.with_database(restored).sqlalchemy_url()

    # 1. Wartung (Live-DB) und Fence: niemand schreibt mehr.
    if not cp.get("window_live"):
        window = maintenance_service.create_window(
            db, kind="full", reason_code="backup_restore", state="preparing", affected_features=["all"],
            source_job_type="backup_restore", source_job_id=str(job.id), release_conditions=[],
        )
        db.commit()
        cp = jobs.checkpoint(db, ctx, window_live=str(window.id), pre_restore_db=pre)
    window = maintenance_service.lock_window(db, uuid.UUID(cp["window_live"]))
    if window.state == "preparing":
        maintenance_service.transition(db, window, "active", details={"source": "backup_restore"})
    db.commit()
    time.sleep(max(2 * float(os.environ.get("MAINTENANCE_CACHE_SECONDS", "2")), 1) + 3)
    db.execute(text(f"SET LOCAL lock_timeout = '{CUTOVER_LOCK_TIMEOUT}'"))
    db.execute(text("""
        UPDATE storage_state SET write_fenced = true, fence_reason = :reason, fence_token = fence_token + 1, fenced_at = NOW(), updated_at = NOW()
        WHERE id = 1
    """), {"reason": f"restore:{job.id}"})
    db.commit()
    if not cp.get("window_restored"):
        cp = jobs.checkpoint(db, ctx, window_restored=str(_insert_window(restored_url, job.id)))
    jobs.set_state(db, ctx, "cutover", message="Wartung aktiv, Datenbanken werden getauscht")

    # 2. Backup-Verwaltung in die wiederhergestellte DB übernehmen (Historie, laufender Auftrag).
    work = env.config.staging_dir / f"restore-{ctx.job_id.hex}"
    work.mkdir(parents=True, exist_ok=True)
    tables_dump = work / "backup-tables.pgdump"
    with PgTools(target) as pg:
        pg._run(["pg_dump", "--format=custom", "--data-only", *[f"--table=public.{t}" for t in BACKUP_TABLES],
                 f"--file={tables_dump}", f"--dbname={live}"], timeout=3600)
        pg.psql("SET session_replication_role = replica;\nTRUNCATE " + ", ".join(BACKUP_TABLES) + " CASCADE;", database=restored)
        pg._run(["pg_restore", "--data-only", "--disable-triggers", "--exit-on-error", f"--dbname={restored}", str(tables_dump)], timeout=3600)
        tables_dump.unlink(missing_ok=True)
        _write_journal(journal_path, {"job_id": str(ctx.job_id), "live": live, "restored": restored, "pre": pre, "step": "copied"})
        # 3. Tausch per Umbenennen - vorher alle Verbindungen sperren und beenden.
        for name in (live, restored):
            pg.psql(f'ALTER DATABASE "{validate_db_name(name)}" WITH ALLOW_CONNECTIONS false;', database="postgres")
        for attempt in range(10):
            pg.psql(f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname IN ('{live}', '{restored}') AND pid <> pg_backend_pid();",
                    database="postgres")
            try:
                pg.psql(f'ALTER DATABASE "{live}" RENAME TO "{validate_db_name(pre)}";', database="postgres")
                break
            except Exception:  # noqa: BLE001 - Verbindung noch nicht weg: erneut
                if attempt == 9:
                    for name in (live, restored):
                        pg.psql(f'ALTER DATABASE "{name}" WITH ALLOW_CONNECTIONS true;', database="postgres")
                    raise
                time.sleep(1)
        _write_journal(journal_path, {"job_id": str(ctx.job_id), "live": live, "restored": restored, "pre": pre, "step": "renamed_live"})
        pg.psql(f'ALTER DATABASE "{restored}" RENAME TO "{live}";', database="postgres")
        _write_journal(journal_path, {"job_id": str(ctx.job_id), "live": live, "restored": restored, "pre": pre, "step": "renamed_restored"})
        pg.psql(f'ALTER DATABASE "{live}" WITH ALLOW_CONNECTIONS true;', database="postgres")
    env.engine.dispose()
    return _after_swap(env, ctx, job, cp, {"live": live, "restored": restored, "pre": pre}, journal_path)


def _after_swap(env: RunEnv, ctx: jobs.JobCtx, job: BackupRestoreJob, cp: dict[str, Any], journal: dict[str, Any], journal_path: Path) -> str:
    """Läuft gegen die NEUE Live-Datenbank (Kopie des Auftrags mit demselben Fencing-Token)."""
    from app.core.db import SessionLocal
    from app.services import maintenance_service

    target = PgTarget.from_url(env.database_url)
    live, pre = journal["live"], journal["pre"]
    problems: list[str] = []
    smoke = smoke_test_database(target.sqlalchemy_url())
    if not smoke["ok"]:
        problems += smoke["problems"]
    env.store.invalidate()
    sample_ok = True
    with SessionLocal() as db:
        state = db.get(StorageState, 1)
        if state.active_generation != cp["generation"] or state.write_fenced:
            problems.append("storage_state")
        # Stichprobe über den regulären Lesepfad der Anwendung.
        rows = db.execute(text("SELECT namespace, key, size_bytes, sha256 FROM storage_object WHERE status = 'active' ORDER BY random() LIMIT 25")).all()
        for row in rows:
            try:
                if not env.store.verify(row.namespace, row.key, sha256=row.sha256, size=row.size_bytes, full=True):
                    sample_ok = False
            except Exception:  # noqa: BLE001 - als Befund
                sample_ok = False
        if not sample_ok:
            problems.append("object_sample")
    if problems:
        return _rollback_swap(env, ctx, job, cp, journal, journal_path, problems)
    with SessionLocal() as db:
        ctx_job = jobs.load(db, ctx)
        try:
            maintenance_service.release(db, uuid.UUID(cp["window_restored"]), actor_email=None, source="job")
            db.commit()
        except maintenance_service.MaintenanceError:
            db.rollback()
            db.execute(text("UPDATE maintenance_window SET state = 'completed', ended_at = NOW() WHERE id = :id"), {"id": cp["window_restored"]})
            db.commit()
        jobs.guarded(db, ctx, result={**(ctx_job.result or {}), "pre_restore_db": pre, "generation": cp["generation"], "smoke": smoke})
        jobs.event(db, ctx, "cutover_done", f"Wiederherstellung aktiv. Bisherige Datenbank: {pre}, neue Generation {cp['generation']}")
        db.commit()
        jobs.set_state(db, ctx, "completed", message="Voll-Restore abgeschlossen")
    journal_path.unlink(missing_ok=True)
    shutil.rmtree(env.config.staging_dir / f"restore-{ctx.job_id.hex}", ignore_errors=True)
    return "completed"


def _rollback_swap(env: RunEnv, ctx: jobs.JobCtx, job: BackupRestoreJob, cp: dict[str, Any], journal: dict[str, Any], journal_path: Path,
                   problems: list[str]) -> str:
    from app.core.db import SessionLocal

    target = PgTarget.from_url(env.database_url)
    live, pre = journal["live"], journal["pre"]
    failed = f"hocx_failed_restore_{ctx.job_id.hex[:12]}"
    with PgTools(target) as pg:
        for name in (live, pre):
            pg.psql(f'ALTER DATABASE "{name}" WITH ALLOW_CONNECTIONS false;', database="postgres")
        pg.psql(f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname IN ('{live}', '{pre}') AND pid <> pg_backend_pid();", database="postgres")
        pg.psql(f'ALTER DATABASE "{live}" RENAME TO "{failed}";', database="postgres")
        pg.psql(f'ALTER DATABASE "{pre}" RENAME TO "{live}";', database="postgres")
        pg.psql(f'ALTER DATABASE "{live}" WITH ALLOW_CONNECTIONS true;', database="postgres")
    env.engine.dispose()
    journal_path.unlink(missing_ok=True)
    with SessionLocal() as db:
        db.execute(text("UPDATE storage_state SET write_fenced = false, fence_reason = NULL, fenced_at = NULL WHERE id = 1 AND fence_reason = :r"),
                   {"r": f"restore:{job.id}"})
        db.commit()
        from app.services import maintenance_service

        try:
            maintenance_service.release(db, uuid.UUID(cp["window_live"]), actor_email=None, source="job")
            db.commit()
        except maintenance_service.MaintenanceError:
            db.rollback()
        jobs.event(db, ctx, "rolled_back", f"Smoke-Test nach dem Tausch fehlgeschlagen ({', '.join(problems)}) - bisherige Datenbank wieder aktiv. "
                   f"Fehlgeschlagene Wiederherstellung liegt in {failed}.", level="error")
        db.commit()
        jobs.set_state(db, ctx, "rolled_back", message="Zurückgetauscht", level="error", error_code="smoke_test_failed",
                       error_message=", ".join(problems)[:500])
    return "rolled_back"


def cleanup_failed_full_restore(env: RunEnv, db: Session, job: BackupRestoreJob) -> None:
    """Fehler VOR dem Tausch: Live-Zustand war nie berührt; Zwischenstände entfernen."""
    cp = job.checkpoint or {}
    if cp.get("restore_db"):
        with PgTools(PgTarget.from_url(env.database_url)) as pg:
            try:
                pg.drop_database(cp["restore_db"])
            except Exception:  # noqa: BLE001 - sichtbar im Log, nicht kritisch
                _logger.warning("Restore-Datenbank %s nicht gelöscht", cp["restore_db"], exc_info=True)
    if cp.get("generation") and cp.get("profile_id"):
        generation = db.scalars(select(StorageGeneration).where(StorageGeneration.generation == cp["generation"])).first()
        if generation is not None and generation.status == "preparing":
            profile = db.get(StorageProfile, cp["profile_id"])
            try:
                purge_generation_objects(env.store.make_backend(env.profile_config(profile, cp["generation"])))
                generation.status = "abandoned"
            except Exception:  # noqa: BLE001 - Generation bleibt zur manuellen Bereinigung stehen
                generation.status = "abandoned"
                generation.purge_error = "Objekte des abgebrochenen Restores konnten nicht gelöscht werden"
    if cp.get("window_live"):
        from app.services import maintenance_service

        db.execute(text("UPDATE storage_state SET write_fenced = false, fence_reason = NULL, fenced_at = NULL WHERE id = 1 AND fence_reason = :r"),
                   {"r": f"restore:{job.id}"})
        try:
            maintenance_service.release(db, uuid.UUID(cp["window_live"]), actor_email=None, source="job")
        except maintenance_service.MaintenanceError:
            pass
    db.commit()
    shutil.rmtree(env.config.staging_dir / f"restore-{job.id.hex}", ignore_errors=True)


def recover_interrupted_cutover(env: RunEnv) -> list[str]:
    """Beim Start des Workers, VOR jedem Datenbankzugriff: ein abgebrochener Datenbanktausch wird
    so aufgelöst, dass wieder eine erreichbare Live-Datenbank existiert."""
    journal_dir = env.config.work_dir / "restore-journal"
    if not journal_dir.is_dir():
        return []
    actions: list[str] = []
    target = PgTarget.from_url(env.database_url)
    with PgTools(target) as pg:
        for path in journal_dir.glob("*.json"):
            data = json.loads(path.read_text())
            live, restored, pre, step = data["live"], data["restored"], data["pre"], data["step"]
            if step == "renamed_live" and not pg.database_exists(live) and pg.database_exists(pre):
                # Live-DB umbenannt, neue noch nicht an ihrem Platz: zurück auf den bekannten Stand.
                pg.psql(f'ALTER DATABASE "{pre}" RENAME TO "{live}";', database="postgres")
                actions.append(f"{pre} -> {live} zurückbenannt")
                step = "copied"
            if pg.database_exists(live):
                pg.psql(f'ALTER DATABASE "{live}" WITH ALLOW_CONNECTIONS true;', database="postgres")
            if step == "copied":
                if pg.database_exists(restored):
                    pg.psql(f'ALTER DATABASE "{restored}" WITH ALLOW_CONNECTIONS true;', database="postgres")
                path.unlink(missing_ok=True)
                actions.append(f"Tausch für Auftrag {data['job_id']} wird neu begonnen")
            # step == renamed_restored: Tausch vollständig; der Auftrag setzt nach dem Tausch fort.
    return actions


def run_full_restore(env: RunEnv, db: Session, ctx: jobs.JobCtx) -> str:
    job = jobs.load(db, ctx)
    cp = dict(job.checkpoint or {})
    phase = cp.get("phase") or "rescue"
    if job.state == "queued":
        jobs.set_state(db, ctx, "preparing", message="Restore wird vorbereitet")
    if phase == "rescue":
        _rescue(env, db, ctx, job)
        job = jobs.load(db, ctx)
        cp = dict(job.checkpoint or {})
        phase = cp.get("phase")
    view = RepositoryView(env.borg)
    if phase != "cutover":
        preflight_repository(env, db)
    if phase == "prepare":
        cp = _prepare(env, db, ctx, job, view)
        phase = "database"
    cp = dict(jobs.load(db, ctx).checkpoint or {})
    if phase in ("database", "objects", "verify"):
        jobs.set_state(db, ctx, "running", message=f"Phase {phase}")
    if phase == "database":
        _database(env, db, ctx, job, view, cp)
        phase = "objects"
    if phase == "objects":
        _objects(env, db, ctx, job, view, cp)
        phase = "verify"
    if phase == "verify":
        jobs.set_state(db, ctx, "verifying", message="Prüfung der Wiederherstellung")
        _verify(env, db, ctx, job, view, cp)
        phase = "cutover"
    cp = dict(jobs.load(db, ctx).checkpoint or {})
    return _cutover(env, db, ctx, job, cp)


# --- Mandant als Kopie ------------------------------------------------------------------------


def run_tenant_copy(env: RunEnv, db: Session, ctx: jobs.JobCtx) -> str:
    from app.core.storage import get_object_store
    from app.services.tenant_import_service import TenantImportService
    from app.models import Tenant

    job = jobs.load(db, ctx)
    options = job.options or {}
    cp = dict(job.checkpoint or {})
    source_tenant_id = int(options["source_tenant_id"])
    new_name = str(options["new_name"]).strip()
    jobs.set_state(db, ctx, "running", message="Mandant wird aus dem Sicherungspunkt gelesen")
    preflight_repository(env, db)
    view = RepositoryView(env.borg)
    metadata = load_restore_point(view, job.archive_name)
    compat = schema_compatibility(metadata.get("alembic_revision"))
    if compat["state"] in ("newer", "unknown"):
        raise jobs.JobFailure("schema_incompatible", "Das Backup stammt von einer neueren/unbekannten hocX-Version")
    work = env.config.staging_dir / f"tenant-{ctx.job_id.hex}"
    work.mkdir(parents=True, exist_ok=True)
    target = PgTarget.from_url(env.database_url)
    temp_db = f"hocx_tsrc_{ctx.job_id.hex[:12]}"
    temp_url = target.with_database(temp_db).sqlalchemy_url()
    store = get_object_store()

    # Ein abgebrochener Import eines früheren Versuchs: halben Mandanten entfernen.
    if cp.get("created_tenant_id"):
        stale = db.get(Tenant, int(cp["created_tenant_id"]))
        if stale is not None:
            db.delete(stale)
            db.commit()
        TenantImportService()._remove_imported_objects_for(db, int(cp["created_tenant_id"]))
        cp = jobs.checkpoint(db, ctx, created_tenant_id=None)

    with PgTools(target) as pg:
        try:
            if pg.database_exists(temp_db):
                pg.drop_database(temp_db)
            jobs.progress(db, ctx, phase="database")
            restore_database(view, job.archive_name, metadata, pg, temp_db, work, max_bytes=env.config.staging_max_bytes,
                             jobs=env.config.pg_restore_jobs)
            if compat["state"] == "upgrade":
                jobs.progress(db, ctx, phase="alembic")
                run_alembic_upgrade(temp_url)

            # Verfügbare Objekte des Sicherungspunkts (nur Keys + Inhalt) für die Export-Logik.
            jobs.progress(db, ctx, phase="collect")
            available: dict[tuple[str, str], tuple[str, int, str]] = {}
            for chunk in iter_manifest_slices(view, job.archive_name, metadata, work):
                for entry in chunk:
                    available[(entry.namespace, entry.key)] = (entry.sha256, entry.size, entry.pool)
            temp_engine = create_engine(temp_url, poolclass=NullPool)
            try:
                with Session(temp_engine) as temp_session:
                    if temp_session.get(Tenant, source_tenant_id) is None:
                        raise jobs.JobFailure("tenant_not_in_backup", "Der Mandant ist in diesem Sicherungspunkt nicht enthalten")
                    exporter = HistoricalTenantExport(set(available))
                    manifest, pending = exporter.collect(temp_session, source_tenant_id, "full_abgabebox")
            finally:
                temp_engine.dispose()
        finally:
            try:
                pg.drop_database(temp_db)
            except Exception:  # noqa: BLE001 - best effort, im Log sichtbar
                _logger.warning("Temporäre Datenbank %s nicht gelöscht", temp_db, exc_info=True)
    manifest, excluded_tables = prepare_copy_manifest(manifest)
    members: dict[str, tuple[str, str, int]] = {}
    needed = []
    from app.backup.manifest import ManifestEntry

    for namespace, key, member in pending:
        sha, size, pool = available[(namespace, key)]
        members[member] = (namespace, sha, size)
        needed.append(ManifestEntry(namespace, key, size, sha, 1, pool))
    total_bytes = sum(entry.size for entry in {e.sha256: e for e in needed}.values())
    jobs.event(db, ctx, "collected", f"{len(pending)} Dateien ({total_bytes} Bytes) des Mandanten im Sicherungspunkt",
               files=len(pending), bytes=total_bytes, excluded_tables=excluded_tables)
    db.commit()

    # Inhalte direkt aus Borg in den Restore-Bereich des aktiven Speichers (nach SHA-256 benannt).
    state_before = store.active_state(force=True)
    backend = store.active_backend(force=True)
    jobs.progress(db, ctx, phase="objects", files=len(pending), bytes_total=total_bytes)
    report = view.fetch_contents(needed, write_contents_sink(backend, key_for=lambda e: (e.namespace, staging_key(ctx.job_id, e.sha256))),
                                 should_stop=ctx.check)
    try:
        if not report.ok:
            raise jobs.JobFailure("objects_incomplete", f"{len(report.missing)} Dateien fehlen, {len(report.corrupt)} beschädigt")
        if store.active_state(force=True).config.cache_key() != state_before.config.cache_key():
            raise jobs.JobFailure("storage_changed", "Der aktive Speicher hat während des Restores gewechselt - bitte erneut starten")
        jobs.progress(db, ctx, phase="import")
        source = RecoveryFileSource(store, backend, ctx.job_id, members, work)
        importer = TenantImportService()
        importer.on_tenant_created = lambda tenant_id: jobs.checkpoint(db, ctx, created_tenant_id=tenant_id)
        new_tenant, warnings = importer.import_manifest(db, manifest, source, new_name)
        jobs.checkpoint(db, ctx, created_tenant_id=None)
        jobs.set_state(db, ctx, "verifying", message="Prüfung des importierten Mandanten")
        check = verify_tenant_files(db, store, new_tenant.id)
        result = {"tenant_id": new_tenant.id, "tenant_public_id": str(new_tenant.public_id), "tenant_name": new_tenant.name,
                  "files_expected": len(pending), "files_imported": source.stored, "warnings": warnings[:200],
                  "excluded_tables": excluded_tables, "source_tenant_id": source_tenant_id, "file_check": check}
        if check["missing"]:
            raise jobs.JobFailure("tenant_files_missing", f"{check['missing']} Dateien des neuen Mandanten fehlen im Speicher")
        jobs.guarded(db, ctx, result=result)
        db.commit()
    finally:
        try:
            purge_staging(backend, ctx.job_id)
        except Exception:  # noqa: BLE001 - Restbereich räumt der nächste Lauf/Retention, im Log sichtbar
            _logger.warning("Restore-Bereich %s nicht vollständig gelöscht", ctx.job_id, exc_info=True)
        shutil.rmtree(work, ignore_errors=True)
    jobs.set_state(db, ctx, "completed", message=f"Mandant als '{new_tenant.name}' wiederhergestellt")
    return "completed"


def verify_tenant_files(db: Session, store: Any, tenant_id: int) -> dict[str, int]:
    """Jede Datei des neuen Mandanten liegt im aktiven Speicher."""
    from app.models import StoredFile, SubmissionUploadFile, Tenant

    abgabebox_ids = set(db.scalars(select(SubmissionUploadFile.stored_file_id)))
    checked = missing = 0
    for file_id, path in db.execute(select(StoredFile.id, StoredFile.storage_path).where(StoredFile.tenant_id == tenant_id)).all():
        checked += 1
        if not store.exists("abgabebox" if file_id in abgabebox_ids else "main", path):
            missing += 1
    logo = db.scalar(select(Tenant.profile_image_path).where(Tenant.id == tenant_id))
    if logo:
        checked += 1
        missing += 0 if store.exists("main", logo) else 1
    return {"checked": checked, "missing": missing}


def cleanup_failed_tenant_copy(env: RunEnv, db: Session, job: BackupRestoreJob) -> None:
    from app.core.storage import get_object_store
    from app.models import Tenant
    from app.services.tenant_import_service import TenantImportService

    cp = job.checkpoint or {}
    if cp.get("created_tenant_id"):
        stale = db.get(Tenant, int(cp["created_tenant_id"]))
        if stale is not None:
            db.delete(stale)
            db.commit()
        TenantImportService()._remove_imported_objects_for(db, int(cp["created_tenant_id"]))
    try:
        purge_staging(get_object_store().active_backend(force=True), job.id)
    except Exception:  # noqa: BLE001 - best effort
        _logger.warning("Restore-Bereich %s nicht gelöscht", job.id, exc_info=True)
    shutil.rmtree(env.config.staging_dir / f"tenant-{job.id.hex}", ignore_errors=True)


__all__ = ["run_full_restore", "run_tenant_copy", "recover_interrupted_cutover", "cleanup_failed_full_restore", "cleanup_failed_tenant_copy"]
