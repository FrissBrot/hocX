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
requires_sshd = pytest.mark.skipif(not (shutil.which("sshd") or Path("/usr/sbin/sshd").exists()), reason="sshd nicht installiert")


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
        sshd = shutil.which("sshd") or "/usr/sbin/sshd"
        self.process = subprocess.Popen([sshd, "-D", "-e", "-f", str(config)], stderr=subprocess.PIPE)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with socket.socket() as sock:
                if sock.connect_ex(("127.0.0.1", self.port)) == 0:
                    break
            time.sleep(0.1)
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

    def stop(self) -> None:
        self.process.terminate()
        self.process.wait(timeout=10)
