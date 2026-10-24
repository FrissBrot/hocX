"""Fehlerfälle und Last: Verbindungsabbruch zur Storage Box mitten im Backup, falscher
SSH-Schlüssel, beschädigtes Repository, zu wenig lokaler Platz, und ein grosser simulierter
Objektbestand, bei dem der lokale Speicherbedarf gemessen wird."""

from __future__ import annotations

import os
import threading
import time
import uuid
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import update

from app.backup import jobs
from app.backup.borg import Borg, BorgError
from app.core.db import SessionLocal, engine
from app.core.storage import get_object_store
from app.models import BackupJob, BackupSet, StorageState
from app.workers import backup_worker
from tests.backup_support import SshBorgServer, backup_env, put_object, requires_borg, requires_sshd, run_backup_job  # noqa: F401
from tests.storage_support import committed_storage, requires_s3  # noqa: F401

pytestmark = [requires_borg, requires_s3]


def _job(kind: str = "backup") -> uuid.UUID:
    with SessionLocal() as db:
        db.execute(update(BackupJob).where(BackupJob.state == "queued").values(state="cancelled"))
        job = BackupJob(kind=kind, trigger="manual")
        db.add(job)
        db.commit()
        return job.id


def _drive_once(env) -> None:
    ctx = jobs.claim(engine, BackupJob, "test")
    assert ctx is not None
    backup_worker.run_job(env, ctx)


@requires_sshd
def test_connection_loss_mid_backup_is_retried_and_resumes(backup_env, tmp_path, monkeypatch):  # noqa: F811
    db, env, _ = backup_env
    server = SshBorgServer(tmp_path / "box")
    try:
        config = server.config(tmp_path / "client", batch_max_objects=2)
        Borg(server.config(tmp_path / "maint", maintenance=True)).init()
        env.borg = Borg(config)
        env.config = config
        for i in range(6):
            put_object(db, f"uploads/ssh/{i}.bin", os.urandom(4096))
        from app.backup import index as index_module

        real_add_pool = index_module.ContentIndex.add_pool
        calls = {"n": 0}

        def cut_connection_after_first_pool(self, *args, **kwargs):
            real_add_pool(self, *args, **kwargs)
            calls["n"] += 1
            if calls["n"] == 1:
                server.stop()  # Storage Box weg (z. B. Netzausfall)

        monkeypatch.setattr(index_module.ContentIndex, "add_pool", cut_connection_after_first_pool)
        job_id = _job()
        _drive_once(env)
        db.expire_all()
        job = db.get(BackupJob, job_id)
        assert job.state == "queued" and job.error_code in ("borg_repository_unreachable", "borg_connection_lost")
        assert job.attempt == 1
        # Hold und Staging bleiben für die Fortsetzung erhalten.
        assert db.get(StorageState, 1, populate_existing=True).backup_hold_id is not None
        server.start()
        db.execute(update(BackupJob).where(BackupJob.id == job_id).values(next_attempt_at=None))
        db.commit()
        _drive_once(env)
        db.expire_all()
        job = db.get(BackupJob, job_id)
        assert job.state == "completed", (job.error_code, job.error_message)
        assert db.get(BackupSet, job.backup_set_id).object_count == 6
        assert db.get(StorageState, 1, populate_existing=True).backup_hold_id is None
    finally:
        server.stop()


@requires_sshd
def test_unknown_ssh_key_is_rejected(tmp_path):
    server = SshBorgServer(tmp_path / "box")
    try:
        stranger = tmp_path / "stranger"
        import subprocess

        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(stranger)], check=True)
        with pytest.raises(BorgError) as info:
            Borg(server.config(tmp_path / "c", ssh_key_file=stranger)).list_archives()
        assert info.value.code == "ssh_auth_failed"
        assert not info.value.transient
    finally:
        server.stop()


def test_corrupted_repository_fails_verification(backup_env):  # noqa: F811
    db, env, _ = backup_env
    put_object(db, "uploads/c/x.bin", os.urandom(200_000))
    assert run_backup_job(env).state == "completed"
    repo = Path(env.config.repository_url)
    segments = sorted(p for p in (repo / "data").rglob("*") if p.is_file() and p.name.isdigit() and p.stat().st_size > 100_000)
    target = segments[-1]
    data = bytearray(target.read_bytes())
    for offset in range(len(data) // 2, len(data) // 2 + 64):
        data[offset] ^= 0xFF
    target.write_bytes(bytes(data))
    verify = run_backup_job(env, "verify")
    assert verify.state == "failed"
    assert verify.error_code.startswith("borg_") or verify.error_code == "verification_failed"


def test_insufficient_local_space_fails_cleanly(backup_env):  # noqa: F811
    db, env, _ = backup_env
    put_object(db, "uploads/s/x.bin", b"x")
    env.config = replace(env.config, staging_max_bytes=64 * 1024 * 1024)
    import app.backup.run_backup as run_backup_module

    original = run_backup_module._free_bytes
    run_backup_module._free_bytes = lambda path: 1024  # fast voller Datenträger
    try:
        job = run_backup_job(env)
    finally:
        run_backup_module._free_bytes = original
    assert job.state == "failed" and job.error_code == "staging_insufficient"
    assert db.get(StorageState, 1, populate_existing=True).backup_hold_id is None


def _dir_size(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def test_large_object_set_needs_no_local_mirror(backup_env, capsys):  # noqa: F811
    """2000 Objekte mit zusammen ~160 MiB, darunter einzelne Objekte grösser als ein Batch: der
    lokale Platz (Staging + Borg-Cache) bleibt weit unter der Datenmenge und wächst bei der
    Folgesicherung nicht mit."""
    db, env, _ = backup_env
    env.config = replace(env.config, batch_max_bytes=16 * 1024 * 1024, batch_max_objects=500)
    store = get_object_store()
    total = 0
    with SessionLocal() as writer:
        for i in range(2000):
            size = 40_000 if i % 100 else 2_500_000  # alle 100 ein grösseres Objekt
            payload = os.urandom(size)
            store.put_bytes(writer, "main", f"uploads/load/{i:05d}.bin", payload)
            total += size
            if i % 200 == 0:
                writer.commit()
        writer.commit()
    peak = {"staging": 0}
    stop = threading.Event()

    def sample() -> None:
        while not stop.is_set():
            peak["staging"] = max(peak["staging"], _dir_size(env.config.staging_dir))
            time.sleep(0.05)

    sampler = threading.Thread(target=sample, daemon=True)
    sampler.start()
    started = time.monotonic()
    first = run_backup_job(env)
    first_seconds = time.monotonic() - started
    stop.set()
    sampler.join()
    assert first.state == "completed", first.error_message
    first_set = db.get(BackupSet, first.backup_set_id)
    cache = _dir_size(env.config.borg_base_dir)
    dump = first_set.db_dump_bytes or 0
    # Staging enthält nur Dump, Inventar und Manifest - nie Objektinhalte.
    assert peak["staging"] < dump + 32 * 1024 * 1024
    assert peak["staging"] < total / 4
    assert cache < total / 4

    started = time.monotonic()
    second = run_backup_job(env)
    second_seconds = time.monotonic() - started
    second_set = db.get(BackupSet, second.backup_set_id)
    assert second_set.new_object_count == 0 and second_set.object_count == first_set.object_count
    with capsys.disabled():
        print(f"\n[Lasttest] Objekte: {first_set.object_count}, Daten: {total / 1024 ** 2:.1f} MiB, "
              f"Staging-Spitze: {peak['staging'] / 1024 ** 2:.2f} MiB (Dump {dump / 1024 ** 2:.2f} MiB), "
              f"Borg-Cache: {cache / 1024 ** 2:.2f} MiB, Erstsicherung {first_seconds:.1f} s, "
              f"Folgesicherung {second_seconds:.1f} s ({second_set.new_object_count} neue Objekte)")
