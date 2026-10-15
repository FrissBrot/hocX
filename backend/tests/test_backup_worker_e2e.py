"""End-to-End des Backup-Workers gegen echte Komponenten: Test-Datenbank, isoliertes Test-S3
(Garage, docker-compose.tests.yml) und ein lokales Borg-1.4-Repository. Ersetzt die Hetzner
Storage Box durch ein lokales Repository (SSH-Transport ist in test_backup_borg.py abgedeckt)."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, update

from app.backup import jobs
from app.core.db import SessionLocal, engine
from app.core.storage import get_object_store
from app.models import BackupContent, BackupJob, BackupPoolArchive, BackupSet, BackupSettings, StorageGeneration, StorageState, StoredFile
from app.models import StorageObject
from app.workers import backup_worker
from tests.backup_support import archive_contents as _contents
from tests.backup_support import backup_env  # noqa: F401 - Fixture
from tests.backup_support import put_object as _put
from tests.backup_support import requires_borg
from tests.backup_support import run_backup_job as _run
from tests.storage_support import committed_storage, make_committed_tenant, requires_s3  # noqa: F401 - Fixture

pytestmark = [requires_borg, requires_s3]


def test_first_and_incremental_backup(backup_env, monkeypatch):
    db, env, generation = backup_env
    tenant = make_committed_tenant(db, "Backup")
    keys = [f"uploads/tenant-{tenant.id}/gallery/{i}.jpg" for i in range(5)]
    for i, key in enumerate(keys):
        _put(db, key, f"bild-{i}".encode() * 1000)
    _put(db, "tenant-1/a/b.pdf", b"abgabe", namespace="abgabebox")
    db.add(StoredFile(tenant_id=tenant.id, original_name="x.jpg", storage_path=keys[0]))
    db.commit()

    first = _run(env)
    assert first.state == "completed", (first.error_code, first.error_message)
    backup_set = db.get(BackupSet, first.backup_set_id)
    assert backup_set.object_count == 6 and backup_set.new_object_count == 6
    assert backup_set.generation == generation
    assert any(t["id"] == tenant.id and t["objects"] == 5 for t in backup_set.tenants)
    contents = _contents(env, backup_set.archive_name)
    assert contents[("main", keys[2])] == b"bild-2" * 1000
    assert contents[("abgabebox", "tenant-1/a/b.pdf")] == b"abgabe"
    # Hold gelöst, Staging leer
    state = db.get(StorageState, 1, populate_existing=True)
    assert state.backup_hold_id is None
    assert not any(env.config.staging_dir.glob("job-*"))

    # Folgesicherung: unveränderte Objekte werden nicht erneut gelesen.
    reads: list[str] = []
    original = type(env.store.active_backend()).open_read

    def counting(self, namespace, key, **kwargs):
        reads.append(key)
        return original(self, namespace, key, **kwargs)

    monkeypatch.setattr(type(env.store.active_backend()), "open_read", counting)
    _put(db, f"uploads/tenant-{tenant.id}/gallery/new.jpg", b"neu")
    second = _run(env)
    assert second.state == "completed"
    second_set = db.get(BackupSet, second.backup_set_id)
    assert second_set.object_count == 7 and second_set.new_object_count == 1
    assert reads == [f"uploads/tenant-{tenant.id}/gallery/new.jpg"]


def test_changes_during_transfer_keep_the_snapshot_content(backup_env, monkeypatch):
    """Löschen und Überschreiben NACH dem Snapshot dürfen den Sicherungspunkt nicht verändern
    (Copy-on-Write über den Backup-Hold) - auch ohne Objektversionierung des Anbieters."""
    db, env, _ = backup_env
    _put(db, "document_template_parts/a/part.tex", b"version-1")
    _put(db, "uploads/x/delete-me.bin", b"wird geloescht")
    _put(db, "uploads/x/keep.bin", b"bleibt")
    from app.backup import run_backup

    real_capture = run_backup.capture

    def capture_then_change(*args, **kwargs):
        captured = real_capture(*args, **kwargs)
        with SessionLocal() as writer:
            store = get_object_store()
            store.put_bytes(writer, "main", "document_template_parts/a/part.tex", b"version-2")
            store.delete(writer, "main", "uploads/x/delete-me.bin")
            store.put_bytes(writer, "main", "uploads/x/after-snapshot.bin", b"neu")
            writer.commit()
        return captured

    monkeypatch.setattr(run_backup, "capture", capture_then_change)
    job = _run(env)
    assert job.state == "completed", job.error_message
    contents = _contents(env, db.get(BackupSet, job.backup_set_id).archive_name)
    assert contents[("main", "document_template_parts/a/part.tex")] == b"version-1"
    assert contents[("main", "uploads/x/delete-me.bin")] == b"wird geloescht"
    assert ("main", "uploads/x/after-snapshot.bin") not in contents
    # Hold-Kopien wurden nach dem Lauf entfernt.
    backend = env.store.active_backend(force=True)
    assert not list(backend.list("main", "_hocx-backup-hold/"))


def test_changes_during_transfer_keep_the_snapshot_content_of_unhashed_objects(backup_env, monkeypatch):
    """BORG-005: Registereinträge ohne SHA-256 (Altbestand) werden vor dem Hold nachgehasht -
    Copy-on-Write greift dann auch für sie."""
    db, env, _ = backup_env
    _put(db, "uploads/legacy/old.bin", b"alt-inhalt")
    _put(db, "uploads/legacy/gone.bin", b"wird geloescht")
    db.execute(update(StorageObject).where(StorageObject.key.in_(["uploads/legacy/old.bin", "uploads/legacy/gone.bin"])).values(sha256=None))
    db.commit()
    from app.backup import run_backup

    real_capture = run_backup.capture

    def capture_then_change(*args, **kwargs):
        captured = real_capture(*args, **kwargs)
        with SessionLocal() as writer:
            store = get_object_store()
            store.put_bytes(writer, "main", "uploads/legacy/old.bin", b"neuer-inhalt")
            store.delete(writer, "main", "uploads/legacy/gone.bin")
            writer.commit()
        return captured

    monkeypatch.setattr(run_backup, "capture", capture_then_change)
    job = _run(env)
    assert job.state == "completed", job.error_message
    contents = _contents(env, db.get(BackupSet, job.backup_set_id).archive_name)
    assert contents[("main", "uploads/legacy/old.bin")] == b"alt-inhalt"
    assert contents[("main", "uploads/legacy/gone.bin")] == b"wird geloescht"


def test_missing_object_makes_the_backup_partial(backup_env):
    db, env, _ = backup_env
    _put(db, "uploads/x/ok.bin", b"ok")
    _put(db, "uploads/x/lost.bin", b"lost")
    env.store.active_backend().delete("main", "uploads/x/lost.bin")  # physisch weg, Register sagt "aktiv"
    job = _run(env)
    assert job.state == "partial"
    backup_set = db.get(BackupSet, job.backup_set_id)
    assert backup_set.state == "partial"
    warning = next(w for w in backup_set.warnings if w["code"] == "missing_objects")
    assert warning["count"] == 1 and warning["items"][0]["key"] == "uploads/x/lost.bin"


def test_retention_keeps_the_only_partial_restore_point(backup_env):
    """BORG-001: gibt es nur teilweise erfolgreiche Punkte (dauerhaft fehlendes Objekt), löscht
    die Retention trotzdem nie den jüngsten - auch ohne keep_within-Fenster."""
    db, env, _ = backup_env
    _put(db, "uploads/y/ok.bin", b"ok")
    _put(db, "uploads/y/lost.bin", b"lost")
    env.store.active_backend().delete("main", "uploads/y/lost.bin")
    older = _run(env)
    newer = _run(env)
    assert older.state == newer.state == "partial"
    db.execute(update(BackupSettings).values(keep_within_days=0, keep_daily=1, keep_weekly=0, keep_monthly=0))
    db.execute(update(BackupSet).where(BackupSet.id == older.backup_set_id).values(snapshot_at=datetime.now(UTC) - timedelta(days=40)))
    db.execute(update(BackupSet).where(BackupSet.id == newer.backup_set_id).values(snapshot_at=datetime.now(UTC) - timedelta(days=30)))
    # Die nach dem Backup automatisch eingeplante Retention ersetzt der explizite Lauf unten.
    db.execute(update(BackupJob).where(BackupJob.state == "queued").values(state="cancelled"))
    db.commit()
    retention = _run(env, "retention")
    assert retention.state == "completed", retention.error_message
    db.expire_all()
    kept = db.get(BackupSet, newer.backup_set_id)
    assert kept.state == "partial"
    assert kept.archive_name in {a["name"] for a in env.borg.list_archives()}


def test_interrupted_backup_resumes_without_reuploading(backup_env, monkeypatch):
    db, env, _ = backup_env
    for i in range(7):
        _put(db, f"uploads/r/{i}.bin", f"inhalt-{i}".encode())
    from app.backup import tarstream

    calls = {"n": 0}
    real = tarstream.TarStreamWriter.add_chunks

    def crash_after_first_pool(self, name, size, chunks, **kwargs):
        if name.startswith("pool/"):
            calls["n"] += 1
            if calls["n"] == 5:
                raise KeyboardInterrupt("Worker-Absturz simuliert")
        return real(self, name, size, chunks, **kwargs)

    monkeypatch.setattr(tarstream.TarStreamWriter, "add_chunks", crash_after_first_pool)
    with SessionLocal() as s:
        job = BackupJob(kind="backup", trigger="manual")
        s.add(job)
        s.commit()
        job_id = job.id
    ctx = jobs.claim(engine, BackupJob, "worker-a")
    with pytest.raises(KeyboardInterrupt):
        backup_worker.run_job(env, ctx)
    monkeypatch.setattr(tarstream.TarStreamWriter, "add_chunks", real)
    db.expire_all()
    assert db.get(BackupJob, job_id).state == "running"
    first_pools = db.scalar(select(func.count()).select_from(BackupPoolArchive))
    assert first_pools >= 1
    ctx = jobs.claim(engine, BackupJob, "worker-b")
    assert ctx.resumed
    backup_worker.run_job(env, ctx)
    db.expire_all()
    job = db.get(BackupJob, job_id)
    assert job.state == "completed" and job.attempt == 1
    backup_set = db.get(BackupSet, job.backup_set_id)
    assert backup_set.object_count == 7
    assert backup_set.new_object_count < 7  # Inhalte des ersten Versuchs wurden übernommen
    assert len(_contents(env, backup_set.archive_name)) == 7


def test_cutover_during_backup_reads_the_frozen_generation(backup_env, monkeypatch):
    db, env, generation = backup_env
    _put(db, "uploads/c/a.bin", b"alt")
    from app.backup import run_backup

    real_capture = run_backup.capture

    def capture_then_cutover(*args, **kwargs):
        captured = real_capture(*args, **kwargs)
        with SessionLocal() as s:
            # Cutover auf eine neue (leere) Generation desselben Profils, wie ihn eine Migration macht.
            state = s.get(StorageState, 1)
            s.execute(update(StorageGeneration).where(StorageGeneration.generation == generation).values(status="retained"))
            s.add(StorageGeneration(profile_id=state.active_profile_id, generation=generation + 1, status="active"))
            s.execute(update(StorageState).where(StorageState.id == 1).values(active_generation=generation + 1))
            s.commit()
        get_object_store().invalidate()
        return captured

    monkeypatch.setattr(run_backup, "capture", capture_then_cutover)
    job = _run(env)
    assert job.state == "completed", job.error_message
    backup_set = db.get(BackupSet, job.backup_set_id)
    assert backup_set.generation == generation
    assert _contents(env, backup_set.archive_name)[("main", "uploads/c/a.bin")] == b"alt"


def test_restore_test_verify_and_retention_with_gc(backup_env):
    db, env, _ = backup_env
    _put(db, "uploads/g/keep.bin", b"bleibt")
    _put(db, "uploads/g/old.bin", b"alt" * 100)
    first = _run(env)
    get_object_store().delete(db, "main", "uploads/g/old.bin")
    db.commit()
    second = _run(env)
    assert first.state == second.state == "completed"

    verify = _run(env, "verify", sample=1000)
    assert verify.state == "completed", verify.error_message
    assert db.get(BackupSet, second.backup_set_id, populate_existing=True).verify_state == "verified"

    test = _run(env, "restore_test", objects="all")
    assert test.state == "completed", (test.error_code, test.error_message, test.result)
    tested = db.get(BackupSet, second.backup_set_id, populate_existing=True)
    assert tested.restore_test_state == "passed"
    # Jedes registrierte Objekt wurde wiederhergestellt (Referenzlücken aus anderen Tests in der
    # gemeinsamen Test-DB sind vorbestehend und werden separat ausgewiesen).
    assert tested.restore_test_details["references"]["registry_without_object_count"] == 0

    # Nur der jüngste Punkt bleibt -> der Inhalt von old.bin ist unreferenziert und wird entfernt.
    db.execute(update(BackupSettings).values(keep_within_days=0, keep_daily=1, keep_weekly=0, keep_monthly=0))
    db.execute(update(BackupSet).where(BackupSet.id == first.backup_set_id).values(snapshot_at=datetime.now(UTC) - timedelta(days=3)))
    db.commit()
    retention = _run(env, "retention", force_gc=True)
    assert retention.state == "completed", retention.error_message
    db.expire_all()
    assert db.get(BackupSet, first.backup_set_id).state == "pruned"
    gc = retention.result["gc"]
    assert gc["contents_removed"] == 1
    old_sha = hashlib.sha256(b"alt" * 100).hexdigest()
    assert db.get(BackupContent, old_sha) is None
    names = {a["name"] for a in env.borg.list_archives()}
    assert db.get(BackupSet, first.backup_set_id).archive_name not in names
    # Der behaltene Punkt bleibt vollständig wiederherstellbar.
    assert _contents(env, db.get(BackupSet, second.backup_set_id).archive_name) == {("main", "uploads/g/keep.bin"): b"bleibt"}


def test_scheduler_enqueues_once_per_slot(backup_env):
    db, _env, _ = backup_env
    now = datetime(2026, 10, 15, 7, 0, tzinfo=UTC)
    assert backup_worker.schedule_slot(now, 6, 15) == datetime(2026, 10, 15, 6, 15, tzinfo=UTC)
    assert backup_worker.schedule_slot(datetime(2026, 10, 15, 6, 14, tzinfo=UTC), 6, 15) == datetime(2026, 10, 15, 0, 15, tzinfo=UTC)
    created = backup_worker.schedule_tick(db, now)
    assert "backup" in created
    assert "backup" not in backup_worker.schedule_tick(db, now + timedelta(minutes=5))
    assert db.scalar(select(func.count()).select_from(BackupJob).where(BackupJob.kind == "backup")) == 1


def test_wrong_passphrase_fails_permanently_and_releases_hold(backup_env):
    db, env, _ = backup_env
    _put(db, "uploads/p/a.bin", b"x")
    env.config.passphrase_file.write_text("falsch\n")
    job = _run(env)
    assert job.state == "failed" and job.error_code == "borg_passphrase_wrong"
    assert db.get(StorageState, 1, populate_existing=True).backup_hold_id is None
