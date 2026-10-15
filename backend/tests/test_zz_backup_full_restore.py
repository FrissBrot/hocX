"""Voll-Restore über den Worker mit echtem Datenbanktausch auf der Test-Datenbank.

Läuft bewusst als letzte Testdatei (Name): der Tausch ersetzt die Test-Datenbank durch ihren
wiederhergestellten Stand. Geprüft wird der ganze Ablauf - Rettungspunkt, isolierte Datenbank,
neue Storage-Generation, Referenzprüfung, Wartung, Tausch, Smoke-Test, Freigabe - und der
automatische Rücktausch, wenn der Smoke-Test nach dem Tausch scheitert."""

from __future__ import annotations

import time
import uuid

from sqlalchemy import select, update

from app.backup import jobs
from app.backup import run_restore
from app.backup.pgtools import PgTarget, PgTools
from app.core.config import settings
from app.core.db import SessionLocal, engine
from app.core.storage import get_object_store
from app.models import BackupRestoreJob, BackupSet, BackupSettings, MaintenanceWindow, StorageState, Tenant
from app.models import BackupJob
from app.services import maintenance_service
from app.workers import backup_worker
from tests.backup_support import backup_env  # noqa: F401 - Fixture
from tests.backup_support import put_object, requires_borg, run_backup_job
from tests.storage_support import committed_storage, make_committed_tenant, requires_s3  # noqa: F401 - Fixture

pytestmark = [requires_borg, requires_s3]


def _drive(env, restore_id, timeout: float = 600) -> BackupRestoreJob:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ctx = jobs.claim(engine, BackupJob, "test-worker") or jobs.claim(engine, BackupRestoreJob, "test-worker")
        if ctx is not None:
            backup_worker.run_job(env, ctx)
        else:
            time.sleep(1)
        with SessionLocal() as db:
            job = db.get(BackupRestoreJob, restore_id)
            if job is not None and job.state in jobs.TERMINAL_RESTORE_STATES:
                return job
    raise AssertionError("Restore nicht rechtzeitig fertig")


def _create_restore(archive: str) -> uuid.UUID:
    with SessionLocal() as db:
        db.execute(update(BackupSettings).values(schedule_enabled=False))
        job = BackupRestoreJob(kind="full", archive_name=archive, options={}, requested_by_email="owner@example.com")
        db.add(job)
        db.commit()
        return job.id


def _drop(name: str | None) -> None:
    if name:
        with PgTools(PgTarget.from_url(settings.database_url)) as pg:
            if pg.database_exists(name):
                pg.drop_database(name)


def test_full_restore_with_rollback_when_smoke_test_fails(backup_env, monkeypatch):  # noqa: F811
    db, env, _ = backup_env
    monkeypatch.setattr(settings, "maintenance_cache_seconds", 0.05)
    put_object(db, "uploads/full/a.bin", b"vor dem backup")
    backup = run_backup_job(env)
    archive = db.get(BackupSet, backup.backup_set_id).archive_name
    later = make_committed_tenant(db, "Nach dem Backup")
    db.close()
    real_smoke = run_restore.smoke_test_database
    calls = {"n": 0}

    def smoke_fails_after_swap(url):
        # 1. Aufruf: Prüfung der isolierten Datenbank (vor dem Tausch) - echt; 2.: nach dem Tausch.
        calls["n"] += 1
        return real_smoke(url) if calls["n"] == 1 else {"ok": False, "problems": ["simuliert"]}

    monkeypatch.setattr(run_restore, "smoke_test_database", smoke_fails_after_swap)
    job = _drive(env, _create_restore(archive))
    assert job.state == "rolled_back", (job.error_code, job.error_message)
    with SessionLocal() as s:
        # Live-Zustand unverändert: der Mandant nach dem Backup existiert, nichts ist gesperrt.
        assert s.get(Tenant, later.id) is not None
        assert not s.get(StorageState, 1).write_fenced
        blocking = s.scalars(select(MaintenanceWindow).where(MaintenanceWindow.reason_code == "backup_restore",
                                                             MaintenanceWindow.state.in_(("preparing", "active")))).all()
        assert blocking == []
    _drop(f"hocx_failed_restore_{job.id.hex[:12]}")


def test_full_restore_swaps_database_and_storage_generation(backup_env, monkeypatch):  # noqa: F811
    db, env, generation = backup_env
    monkeypatch.setattr(settings, "maintenance_cache_seconds", 0.05)
    tenant = make_committed_tenant(db, "Restore-Original")
    tenant_id = tenant.id
    put_object(db, f"uploads/tenant-{tenant_id}/bild.jpg", b"original-bild")
    backup = run_backup_job(env)
    archive = db.get(BackupSet, backup.backup_set_id).archive_name
    later = make_committed_tenant(db, "Nach dem Backup")
    later_id = later.id
    db.close()
    restore_id = _create_restore(archive)
    job = _drive(env, restore_id)
    pre = (job.result or {}).get("pre_restore_db")
    try:
        assert job.state == "completed", (job.error_code, job.error_message)
        with SessionLocal() as s:
            # Stand des Backups: der spätere Mandant ist weg, der ursprüngliche da.
            assert s.get(Tenant, later_id) is None
            assert s.get(Tenant, tenant_id) is not None
            state = s.get(StorageState, 1)
            assert state.active_generation > generation and not state.write_fenced
            # Rettungspunkt vor dem Restore ist geschützt und in der Historie (Tabellen übernommen).
            rescue = s.scalars(select(BackupSet).where(BackupSet.trigger == "pre_restore")).all()
            assert rescue and all(r.protected for r in rescue)
            assert s.get(BackupRestoreJob, restore_id).state == "completed"
            open_windows = s.scalars(select(MaintenanceWindow).where(MaintenanceWindow.state.in_(("preparing", "active")))).all()
            assert open_windows == []
        get_object_store().invalidate()
        assert get_object_store().get_bytes("main", f"uploads/tenant-{tenant_id}/bild.jpg") == b"original-bild"
        assert pre and pre.startswith("hocx_pre_restore_")
        with PgTools(PgTarget.from_url(settings.database_url)) as pg:
            assert pg.database_exists(pre)  # bisheriger Stand bleibt für einen Rückweg erhalten
    finally:
        _drop(pre)
