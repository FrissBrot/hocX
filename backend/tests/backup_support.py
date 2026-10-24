"""Hilfen für Backup-Tests: lokales Borg-Repository, optional über SSH (sshd im Testcontainer mit
erzwungenem `borg serve --append-only`) - Ersatz für die Hetzner Storage Box, siehe
docs-site/docs/technik/backup/betrieb.md (Abnahme auf der Storage Box)."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
from dataclasses import replace
from pathlib import Path

import pytest

from app.backup.config import BackupConfig

BORG = shutil.which("borg")


def _borg_14() -> bool:
    if not BORG:
        return False
    out = subprocess.run([BORG, "--version"], capture_output=True, check=False).stdout.decode()
    return out.startswith("borg 1.4.")


requires_borg = pytest.mark.skipif(not _borg_14(), reason="borg 1.4 nicht installiert (Backend-Testimage enthält es)")
requires_sshd = pytest.mark.skipif(
    not (shutil.which("sshd") or Path("/usr/sbin/sshd").exists()) or os.geteuid() != 0,
    reason="sshd nicht installiert oder Test nicht als root (Backend-Testimage)",
)


def local_config(tmp_path: Path, **overrides) -> BackupConfig:
    passphrase = tmp_path / "secrets" / "passphrase"
    passphrase.parent.mkdir(parents=True, exist_ok=True)
    if not passphrase.exists():
        passphrase.write_text("test-passphrase-not-secret\n")
    config = BackupConfig(
        enabled=True, host=None, port=23, user=None, repository_path="repo",
        repository_url_override=str(tmp_path / "repo"), remote_path=None,
        ssh_key_file=None, passphrase_file=passphrase, known_hosts_file=None, host_fingerprint=None,
        expected_repository_id=None, maintenance_ssh_key_file=None, work_dir=tmp_path / "work",
        staging_max_bytes=2 * 1024 ** 3, batch_max_bytes=64 * 1024 * 1024, batch_max_objects=1000,
        upload_ratelimit_kib=0, lock_wait_seconds=30, compression="lz4", quota_bytes=None,
        trust_filesystem_registry=True, pg_restore_jobs=1,
    )
    return replace(config, **overrides)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class SshBorgServer:
    """sshd auf 127.0.0.1 mit zwei Schlüsseln: Backup (append-only) und Wartung (voll)."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.port = _free_port()
        self.repo = root / "storagebox" / "hocx-borg"
        self.repo.parent.mkdir(parents=True)
        ssh_dir = root / "sshd"
        ssh_dir.mkdir()
        os.chmod(ssh_dir, 0o700)
        self.host_key = ssh_dir / "host_ed25519"
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(self.host_key)], check=True)
        self.backup_key = root / "client" / "id_backup"
        self.maintenance_key = root / "client" / "id_maintenance"
        self.backup_key.parent.mkdir()
        for key in (self.backup_key, self.maintenance_key):
            subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True)
        borg = BORG or "borg"
        authorized = ssh_dir / "authorized_keys"
        authorized.write_text(
            f'command="{borg} serve --append-only --restrict-to-repository {self.repo}",restrict {self.backup_key.with_suffix(".pub").read_text().strip()}\n'
            f'command="{borg} serve --restrict-to-repository {self.repo}",restrict {self.maintenance_key.with_suffix(".pub").read_text().strip()}\n'
        )
        os.chmod(authorized, 0o600)
        config = ssh_dir / "sshd_config"
        config.write_text(
            f"Port {self.port}\nListenAddress 127.0.0.1\nHostKey {self.host_key}\nPidFile {ssh_dir / 'sshd.pid'}\n"
            f"AuthorizedKeysFile {authorized}\nPasswordAuthentication no\nKbdInteractiveAuthentication no\n"
            "PermitRootLogin prohibit-password\nStrictModes no\nUsePAM no\nLogLevel ERROR\n"
        )
        Path("/run/sshd").mkdir(exist_ok=True)
        self._sshd_config = config
        self.start()
        self.known_hosts = root / "client" / "known_hosts"
        self.known_hosts.write_text(f"[127.0.0.1]:{self.port} {self.host_key.with_suffix('.pub').read_text().strip()}\n")
        self.fingerprint = subprocess.run(["ssh-keygen", "-lf", str(self.host_key.with_suffix(".pub"))], capture_output=True, check=True).stdout.decode().split()[1]
        self.user = os.environ.get("USER") or subprocess.run(["id", "-un"], capture_output=True, check=True).stdout.decode().strip()

    def config(self, tmp_path: Path, *, maintenance: bool = False, **overrides) -> BackupConfig:
        values = {
            "repository_url_override": None, "host": "127.0.0.1", "port": self.port, "user": self.user,
            "repository_path": str(self.repo), "ssh_key_file": self.maintenance_key if maintenance else self.backup_key,
            "known_hosts_file": self.known_hosts, "remote_path": BORG,
        }
        values.update(overrides)
        return local_config(tmp_path, **values)

    def start(self) -> None:
        sshd = shutil.which("sshd") or "/usr/sbin/sshd"
        self.process = subprocess.Popen([sshd, "-D", "-e", "-f", str(self._sshd_config)], stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with socket.socket() as sock:
                if sock.connect_ex(("127.0.0.1", self.port)) == 0:
                    return
            time.sleep(0.1)

    def stop(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=10)
        # Laufende Sitzungen (borg serve) mit beenden - wie ein Verbindungsabbruch.
        subprocess.run(["pkill", "-f", f"borg serve .*{self.repo}"], check=False)


# --- End-to-End-Umgebung (Test-DB, Test-S3, lokales Borg-Repository) -------------------------

import uuid  # noqa: E402
from datetime import UTC, datetime  # noqa: E402

from sqlalchemy import delete, func, select, update  # noqa: E402

from app.backup import jobs  # noqa: E402
from app.backup.borg import Borg  # noqa: E402
from app.backup.manifest import ManifestEntry  # noqa: E402
from app.backup.repository import RepositoryView  # noqa: E402
from app.backup.restore_core import iter_manifest_slices, load_restore_point  # noqa: E402
from app.backup.run_backup import RunEnv  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.db import SessionLocal, engine  # noqa: E402
from app.core.storage import get_object_store  # noqa: E402
from app.models import (  # noqa: E402
    BackupContent,
    BackupEvent,
    BackupJob,
    BackupPoolArchive,
    BackupRestoreJob,
    BackupSet,
    BackupSettings,
    StorageGeneration,
    StorageState,
)
from app.services.storage_profile_service import profile_config  # noqa: E402
from app.workers import backup_worker  # noqa: E402
from tests.storage_support import committed_storage, create_test_profile  # noqa: E402,F401

@pytest.fixture
def backup_env(committed_storage, tmp_path, monkeypatch):  # noqa: F811
    db = committed_storage
    started = datetime.now(UTC)
    # Aktiver Speicher: frisches Test-S3-Profil in einer neuen Generation (Register vertrauenswürdig).
    profile = create_test_profile(db, f"Backup-Test {uuid.uuid4().hex[:6]}", f"bt-{uuid.uuid4().hex[:8]}")
    generation = int(db.scalar(select(func.max(StorageGeneration.generation))) or 0) + 1
    db.execute(update(StorageGeneration).where(StorageGeneration.status == "active").values(status="retained"))
    db.add(StorageGeneration(profile_id=profile.id, generation=generation, status="active", activated_at=started))
    db.execute(update(StorageState).where(StorageState.id == 1).values(active_profile_id=profile.id, active_generation=generation))
    db.commit()
    get_object_store().invalidate()
    config = local_config(tmp_path, trust_filesystem_registry=False, batch_max_objects=3)
    borg = Borg(config)
    borg.init()
    env = RunEnv(config=config, borg=borg, engine=engine, database_url=settings.database_url, store=get_object_store(),
                 profile_config=profile_config, app_version="test")
    yield db, env, generation
    borg.close()
    db.rollback()
    for model in (BackupEvent, BackupRestoreJob):
        db.execute(delete(model))
    db.execute(update(BackupJob).values(backup_set_id=None))
    db.execute(update(BackupSet).values(job_id=None))
    for model in (BackupJob, BackupContent, BackupPoolArchive, BackupSet):
        db.execute(delete(model))
    db.execute(update(BackupSettings).values(repository_status={}, schedule_enabled=True, keep_within_days=14, keep_daily=14, keep_weekly=8, keep_monthly=12))
    db.execute(update(StorageState).where(StorageState.id == 1).values(backup_hold_id=None, backup_hold_generation=None, backup_hold_since=None))
    db.commit()


def put_object(db, key: str, data: bytes, namespace: str = "main") -> None:
    get_object_store().put_bytes(db, namespace, key, data)
    db.commit()


def run_backup_job(env: RunEnv, kind: str = "backup", **options) -> BackupJob:
    with SessionLocal() as db:
        job = BackupJob(kind=kind, trigger="manual", options=options)
        db.add(job)
        db.commit()
        job_id = job.id
        # Vom Worker automatisch nachgelagerte Aufträge (Retention nach Backup) hier nicht mitlaufen lassen.
        db.execute(update(BackupJob).where(BackupJob.state == "queued", BackupJob.id != job_id).values(state="cancelled"))
        db.commit()
    for _ in range(5):
        ctx = jobs.claim(engine, BackupJob, "test-worker")
        assert ctx is not None and ctx.job_id == job_id
        backup_worker.run_job(env, ctx)
        with SessionLocal() as db:
            job = db.get(BackupJob, job_id)
            if job.state in jobs.TERMINAL_JOB_STATES:
                return job
            db.execute(update(BackupJob).where(BackupJob.id == job_id).values(next_attempt_at=None, lease_expires_at=None))
            db.commit()
    return job


def archive_contents(env: RunEnv, archive: str) -> dict[tuple[str, str], bytes]:
    view = RepositoryView(env.borg)
    metadata = load_restore_point(view, archive)
    entries: list[ManifestEntry] = []
    for chunk in iter_manifest_slices(view, archive, metadata, env.config.staging_dir / "test"):
        entries += chunk
    result: dict[tuple[str, str], bytes] = {}

    def sink(_sha, _size, chunks, targets):
        data = b"".join(chunks)
        for target in targets:
            result[(target.namespace, target.key)] = data

    report = view.fetch_contents(entries, sink)
    assert report.ok
    return result


