"""Wartungsaufträge des Backup-Workers: Retention mit Garbage Collection, Integritätsprüfung und
automatischer Restore-Test (siehe docs-site/docs/technik/backup/architektur.md)."""

from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.backup import jobs
from app.backup.index import ContentIndex
from app.backup.manifest import ManifestEntry, parse_rp_name, pool_path
from app.backup.pgtools import PgTarget, PgTools
from app.backup.repository import RepositoryView, RestorePointInfo
from app.backup.restore_core import (
    RestoreError,
    load_restore_point,
    reference_report,
    restore_database,
    restored_keys_from_manifest,
    run_alembic_upgrade,
    schema_compatibility,
    verify_stream,
)
from app.backup.retention import RestorePoint, RetentionPolicy, select_retained
from app.backup.run_backup import RunEnv, preflight_repository
from app.backup.status import settings_row, update_repository_status
from app.models import BackupContent, BackupJob, BackupPoolArchive, BackupSet

_logger = logging.getLogger("hocx.backup.maintenance")

GC_INTERVAL = timedelta(days=7)
INVALID_KEEP = timedelta(days=7)
# Teilweise referenzierte Pools werden erst verkleinert, wenn sich das lohnt.
RECREATE_MIN_FRACTION = 0.2
RECREATE_MIN_BYTES = 1024 ** 3


# --- Abgleich der Historie mit dem Repository ------------------------------------------------


def sync_sets_from_repository(db: Session, view: RepositoryView, points: list[RestorePointInfo]) -> dict[str, int]:
    """Die Datenbank ist nicht die einzige Quelle der Backup-Historie: Wiederherstellungspunkte
    im Repository ohne Eintrag (z. B. nach einem Datenbank-Restore) werden aus ihren Metadaten
    rekonstruiert; Einträge, deren Archiv fehlt, werden als entfernt markiert."""
    known = {row.archive_name: row for row in db.scalars(select(BackupSet))}
    in_repo = {p.name for p in points}
    added = removed = 0
    for point in points:
        if point.invalid or point.name in known:
            continue
        try:
            metadata = view.read_metadata(point.name)
        except Exception as exc:  # noqa: BLE001 - ein unlesbarer Punkt wird markiert, nicht übersprungen
            db.add(BackupSet(id=point.backup_id, archive_name=point.name, archive_id=point.archive_id, state="invalid",
                             snapshot_at=point.snapshot_at, reconstructed=True, warnings=[{"code": "metadata_unreadable", "detail": str(exc)[:300]}]))
            added += 1
            continue
        storage = metadata.get("storage") or {}
        db.add(BackupSet(
            id=point.backup_id, archive_name=point.name, archive_id=point.archive_id,
            state="partial" if metadata.get("missing_objects") else "completed", trigger=metadata.get("trigger") or "schedule",
            snapshot_at=point.snapshot_at, app_version=metadata.get("app_version"), alembic_revision=metadata.get("alembic_revision"),
            pg_server_version=metadata.get("pg_server_version"), profile_name=storage.get("profile_name"),
            profile_provider=storage.get("provider"), generation=storage.get("generation"), outbox_seq=storage.get("outbox_seq"),
            db_dump_bytes=metadata.get("db_dump_bytes"), db_dump_sha256=metadata.get("db_dump_sha256"),
            manifest_sha256=metadata.get("manifest_sha256"), object_count=int(metadata.get("object_count") or 0),
            object_bytes=int(metadata.get("object_bytes") or 0), tenants=metadata.get("tenants") or [],
            warnings=metadata.get("warnings") or [], reconstructed=True,
        ))
        added += 1
    for name, row in known.items():
        if name not in in_repo and row.state in ("completed", "partial"):
            row.state = "pruned"
            row.pruned_at = row.pruned_at or datetime.now(UTC)
            removed += 1
    db.commit()
    return {"reconstructed": added, "marked_pruned": removed}


# --- Retention --------------------------------------------------------------------------------


def run_retention(env: RunEnv, db: Session, ctx: jobs.JobCtx) -> str:
    job = jobs.load(db, ctx)
    jobs.set_state(db, ctx, "running", message="Retention")
    preflight_repository(env, db)
    view = RepositoryView(env.borg)
    points = view.restore_points(include_invalid=True)
    sync = sync_sets_from_repository(db, view, [p for p in points if not p.invalid])
    rows = {row.archive_name: row for row in db.scalars(select(BackupSet))}
    config = settings_row(db)
    policy = RetentionPolicy(config.keep_within_days, config.keep_daily, config.keep_weekly, config.keep_monthly)
    now = datetime.now(UTC)
    candidates = []
    for point in points:
        if point.invalid:
            continue
        row = rows.get(point.name)
        state = row.state if row is not None and row.state in ("completed", "partial") else "completed"
        candidates.append(RestorePoint(point.name, point.snapshot_at, state, protected=bool(row.protected) if row else False))
    kept = select_retained(candidates, policy, now)
    expired = [p.id for p in candidates if p.id not in kept]
    stale_invalid = [p.name for p in points if p.invalid and now - p.snapshot_at > INVALID_KEEP]
    if candidates and not any(name in kept for name in (c.id for c in candidates if c.state == "completed")) and any(c.state == "completed" for c in candidates):
        raise jobs.JobFailure("retention_inconsistent", "Retention würde keinen vollständigen Wiederherstellungspunkt behalten - abgebrochen")
    checkpoints = view.checkpoint_archives()
    to_delete = expired + stale_invalid + checkpoints
    if to_delete:
        env.borg.delete_archives(to_delete)
    for name in expired:
        row = rows.get(name)
        if row is not None:
            row.state = "pruned"
            row.pruned_at = now
    jobs.event(db, ctx, "retention", f"{len(expired)} Wiederherstellungspunkte entfernt, {len(kept)} behalten",
               removed=expired[:100], kept=len(kept), invalid_removed=len(stale_invalid), checkpoints_removed=len(checkpoints), **sync)
    db.commit()
    result: dict[str, Any] = {"removed": len(expired), "kept": len(kept), "checkpoints_removed": len(checkpoints), **sync}
    status = config.repository_status or {}
    last_gc = status.get("last_gc_at")
    gc_due = (job.options or {}).get("force_gc") or not last_gc or now - datetime.fromisoformat(last_gc) > GC_INTERVAL
    open_backups = db.scalar(select(BackupJob.id).where(BackupJob.kind == "backup", BackupJob.state.in_(jobs.OPEN_JOB_STATES)).limit(1))
    if gc_due and open_backups is None:
        result["gc"] = garbage_collect(env, db, ctx, view)
        update_repository_status(db, last_gc_at=now.isoformat(), last_gc=result["gc"])
    jobs.guarded(db, ctx, result=result)
    db.commit()
    jobs.set_state(db, ctx, "completed", message="Retention abgeschlossen")
    return "completed"


def garbage_collect(env: RunEnv, db: Session, ctx: jobs.JobCtx, view: RepositoryView) -> dict[str, Any]:
    """Entfernt Inhalte, die kein Wiederherstellungspunkt im Repository mehr referenziert.
    Reihenfolge: alle Punkte lesen -> referenzierte Inhalte bestimmen -> Referenzintegrität prüfen
    -> erst dann Index markieren und Archive löschen/verkleinern. Jede Unstimmigkeit bricht ab."""
    jobs.progress(db, ctx, phase="gc_scan")
    points = view.restore_points(include_invalid=True)
    pools = view.pool_archives()
    needed: set[bytes] = set()
    work = env.config.staging_dir / f"gc-{ctx.job_id.hex}"
    for point in points:
        ctx.check()
        metadata = load_restore_point(view, point.name.removesuffix(".invalid")) if not point.invalid else view.read_metadata(point.name)
        with view.open_manifest(point.name, work, expected_sha256=metadata["manifest_sha256"]) as (_, entries):
            for entry in entries:
                if entry.pool not in pools:
                    raise jobs.JobFailure("referential_integrity",
                                          f"{point.name} verweist auf das fehlende Pool-Archiv {entry.pool} - Bereinigung abgebrochen")
                needed.add(bytes.fromhex(entry.sha256))
    plan_delete: list[str] = []
    plan_shrink: dict[str, list[str]] = {}
    removed_shas: list[str] = []
    for pool in sorted(pools):
        ctx.check()
        contents = view.pool_contents(pool)
        unreferenced = [sha for sha in contents if bytes.fromhex(sha) not in needed]
        if not unreferenced:
            continue
        if len(unreferenced) == len(contents):
            plan_delete.append(pool)
            removed_shas += unreferenced
            continue
        unreferenced_bytes = sum(contents[sha] for sha in unreferenced)
        if len(unreferenced) / len(contents) >= RECREATE_MIN_FRACTION or unreferenced_bytes >= RECREATE_MIN_BYTES:
            plan_shrink[pool] = unreferenced
            removed_shas += unreferenced
    index = ContentIndex(db)
    index.mark_gc_pending(removed_shas)
    db.execute(BackupPoolArchive.__table__.update().where(BackupPoolArchive.name.in_(plan_delete + list(plan_shrink))).values(state="gc_pending"))
    db.commit()
    jobs.progress(db, ctx, phase="gc_apply", delete_pools=len(plan_delete), shrink_pools=len(plan_shrink))
    if plan_delete:
        env.borg.delete_archives(plan_delete)
    for pool, shas in plan_shrink.items():
        ctx.check()
        env.borg.recreate_exclude(pool, [pool_path(sha) for sha in shas])
    # Index nach dem tatsächlichen Repository-Zustand neu aufbauen (gc_pending-Pools werden neu gelistet).
    index.remove(removed_shas)
    db.commit()
    reconcile = index.reconcile(view)
    result = {"restore_points": len(points), "referenced_contents": len(needed), "pools_deleted": len(plan_delete),
              "pools_shrunk": len(plan_shrink), "contents_removed": len(removed_shas), "reconcile": {k: v for k, v in reconcile.items() if k != "checkpoints"}}
    jobs.event(db, ctx, "gc", f"Bereinigung: {len(plan_delete)} Pool-Archive gelöscht, {len(plan_shrink)} verkleinert", **result)
    db.commit()
    return result


# --- Integritätsprüfung -----------------------------------------------------------------------


def _latest_set(db: Session, options: dict[str, Any]) -> BackupSet | None:
    if options.get("backup_set_id"):
        return db.get(BackupSet, uuid.UUID(str(options["backup_set_id"])))
    return db.scalars(select(BackupSet).where(BackupSet.state.in_(("completed", "partial"))).order_by(BackupSet.snapshot_at.desc()).limit(1)).first()


def _sample_filter(object_count: int, sample: int):
    salt = secrets.token_bytes(8)
    probability = 1.0 if object_count <= sample else sample / max(object_count, 1)

    def keep(entry: ManifestEntry) -> bool:
        if probability >= 1.0:
            return True
        value = int.from_bytes(hashlib.sha256(salt + entry.sha256.encode()).digest()[:4], "big") / 2 ** 32
        return value < probability

    return keep


def run_verify(env: RunEnv, db: Session, ctx: jobs.JobCtx) -> str:
    job = jobs.load(db, ctx)
    options = job.options or {}
    jobs.set_state(db, ctx, "running", message="Integritätsprüfung")
    preflight_repository(env, db)
    view = RepositoryView(env.borg)
    details: dict[str, Any] = {"started_at": datetime.now(UTC).isoformat()}
    jobs.progress(db, ctx, phase="repository_check")
    env.borg.check(repository_only=True)
    details["repository_check"] = "ok"
    jobs.progress(db, ctx, phase="archive_check")
    env.borg.check(archives_only=True, glob="hocx-rp-*")
    details["archive_check"] = "ok"
    backup_set = _latest_set(db, options)
    if backup_set is None:
        raise jobs.JobFailure("no_backup", "Kein Wiederherstellungspunkt zum Prüfen vorhanden")
    jobs.guarded(db, ctx, backup_set_id=backup_set.id)
    db.commit()
    metadata = load_restore_point(view, backup_set.archive_name)
    work = env.config.staging_dir / f"verify-{ctx.job_id.hex}"
    work.mkdir(parents=True, exist_ok=True)
    try:
        jobs.progress(db, ctx, phase="dump_check")
        dump = work / "check.pgdump"
        view.download(backup_set.archive_name, "db/hocx.pgdump", dump, expected_sha256=metadata["db_dump_sha256"],
                      max_bytes=env.config.staging_max_bytes)
        with PgTools(PgTarget.from_url(env.database_url)) as pg:
            toc = pg.list_dump(dump)
        dump.unlink(missing_ok=True)
        details["dump"] = {"sha256_ok": True, "toc_entries": len(toc)}
        config = settings_row(db)
        sample = int(options.get("sample") or config.verify_sample_objects)
        keep = _sample_filter(int(metadata.get("object_count") or 0), sample)
        jobs.progress(db, ctx, phase="content_sample")
        report = verify_stream(view, backup_set.archive_name, metadata, work, keep=keep, should_stop=ctx.check,
                               progress=lambda values: jobs.progress(db, ctx, phase="content_sample", **values))
        details["content_sample"] = report
        if options.get("deep"):
            jobs.progress(db, ctx, phase="verify_data")
            env.borg.check(verify_data=True)
            details["verify_data"] = "ok"
    finally:
        import shutil

        shutil.rmtree(work, ignore_errors=True)
    ok = bool(report["ok"])
    backup_set.verify_state = "verified" if ok else "failed"
    backup_set.verified_at = datetime.now(UTC)
    backup_set.verify_details = details
    jobs.guarded(db, ctx, result=details)
    db.commit()
    update_repository_status(db, last_verify_at=datetime.now(UTC).isoformat(), last_verify_ok=ok)
    if not ok:
        raise jobs.JobFailure("verification_failed", f"{report['missing_count']} fehlende und {report['corrupt_count']} beschädigte Inhalte in {backup_set.archive_name}")
    jobs.set_state(db, ctx, "completed", message=f"{backup_set.archive_name} geprüft")
    return "completed"


# --- Restore-Test -----------------------------------------------------------------------------


def smoke_test_database(database_url: str) -> dict[str, Any]:
    """Prüft, ob die Anwendung mit der Datenbank arbeiten kann: jede ORM-Tabelle ist mit allen
    erwarteten Spalten abfragbar, Kernabfragen liefern Daten."""
    from app.db.base import Base
    from app.models import AppUser, Tenant

    engine = create_engine(database_url, poolclass=NullPool)
    problems: list[str] = []
    try:
        with Session(engine) as session:
            for table in Base.metadata.sorted_tables:
                try:
                    session.execute(select(*table.columns).limit(1)).all()
                except Exception as exc:  # noqa: BLE001 - als Befund sammeln
                    session.rollback()
                    problems.append(f"{table.name}: {type(exc).__name__}")
            tenants = session.scalar(select(text("COUNT(*)")).select_from(Tenant)) or 0
            users = session.scalar(select(text("COUNT(*)")).select_from(AppUser)) or 0
    finally:
        engine.dispose()
    return {"tables_checked": len(Base.metadata.sorted_tables), "problems": problems[:50], "tenants": int(tenants), "users": int(users), "ok": not problems}


def run_restore_test(env: RunEnv, db: Session, ctx: jobs.JobCtx) -> str:
    job = jobs.load(db, ctx)
    options = job.options or {}
    jobs.set_state(db, ctx, "running", message="Restore-Test in isolierter Umgebung")
    preflight_repository(env, db)
    view = RepositoryView(env.borg)
    backup_set = _latest_set(db, options)
    if backup_set is None:
        raise jobs.JobFailure("no_backup", "Kein Wiederherstellungspunkt für den Restore-Test vorhanden")
    jobs.guarded(db, ctx, backup_set_id=backup_set.id)
    db.commit()
    metadata = load_restore_point(view, backup_set.archive_name)
    compat = schema_compatibility(metadata.get("alembic_revision"))
    if compat["state"] in ("newer", "unknown"):
        raise jobs.JobFailure("schema_incompatible", f"Backup-Schema {compat['revision']} ist dieser hocX-Version unbekannt")
    target = PgTarget.from_url(env.database_url)
    db_name = f"hocx_rtest_{ctx.job_id.hex[:12]}"
    temp_url = target.with_database(db_name).sqlalchemy_url()
    work = env.config.staging_dir / f"rtest-{ctx.job_id.hex}"
    details: dict[str, Any] = {"archive": backup_set.archive_name, "schema": compat}
    started = datetime.now(UTC)
    with PgTools(target) as pg:
        try:
            if pg.database_exists(db_name):
                pg.drop_database(db_name)
            jobs.progress(db, ctx, phase="database")
            details["database"] = restore_database(view, backup_set.archive_name, metadata, pg, db_name, work,
                                                   max_bytes=env.config.staging_max_bytes, jobs=env.config.pg_restore_jobs)
            if compat["state"] == "upgrade":
                jobs.progress(db, ctx, phase="alembic")
                run_alembic_upgrade(temp_url)
                details["alembic_upgraded"] = True
            jobs.progress(db, ctx, phase="objects")
            mode = options.get("objects") or "sample"
            keep = None if mode == "all" else _sample_filter(int(metadata.get("object_count") or 0), max(1000, int(settings_row(db).verify_sample_objects) * 5))
            details["objects"] = {"mode": mode, **verify_stream(view, backup_set.archive_name, metadata, work, keep=keep, should_stop=ctx.check,
                                                                progress=lambda values: jobs.progress(db, ctx, phase="objects", **values))}
            jobs.progress(db, ctx, phase="references")
            corrupt = set(details["objects"].get("corrupt") or [])
            details["references"] = reference_report(temp_url, restored_keys_from_manifest(view, backup_set.archive_name, metadata, work, corrupt))
            jobs.progress(db, ctx, phase="application")
            details["application"] = smoke_test_database(temp_url)
        except RestoreError as exc:
            raise jobs.JobFailure(exc.code, str(exc)) from exc
        finally:
            try:
                pg.drop_database(db_name)
            except Exception:  # noqa: BLE001 - Aufräumen best effort, sichtbar im Log
                _logger.warning("Testdatenbank %s konnte nicht gelöscht werden", db_name, exc_info=True)
            import shutil

            shutil.rmtree(work, ignore_errors=True)
    references = details["references"]
    # Eine Referenzlücke, die schon beim Backup als Warnung bekannt war (Verweis ohne Objekt im
    # Register), ist kein Restore-Fehler - ein Objekt im Register ohne wiederhergestellten Inhalt schon.
    ok = details["objects"]["ok"] and details["application"]["ok"] and references["registry_without_object_count"] == int(metadata.get("missing_objects") or 0)
    details["duration_seconds"] = int((datetime.now(UTC) - started).total_seconds())
    details["ok"] = ok
    backup_set.restore_test_state = "passed" if ok else "failed"
    backup_set.restore_tested_at = datetime.now(UTC)
    backup_set.restore_test_details = details
    jobs.guarded(db, ctx, result=details)
    db.commit()
    update_repository_status(db, last_restore_test_at=datetime.now(UTC).isoformat(), last_restore_test_ok=ok)
    if not ok:
        raise jobs.JobFailure("restore_test_failed", f"Restore-Test von {backup_set.archive_name} fehlgeschlagen")
    jobs.set_state(db, ctx, "completed", message=f"Restore-Test von {backup_set.archive_name} erfolgreich")
    return "completed"


__all__ = ["run_retention", "run_verify", "run_restore_test", "sync_sets_from_repository", "garbage_collect", "smoke_test_database",
           "parse_rp_name", "Path", "BackupContent"]
