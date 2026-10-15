"""Konfiguration des Backup-Workers und der Recovery-CLI aus Umgebungsvariablen und
Docker-Secrets. Secrets werden nur als DATEIPFAD gehalten und erst beim Aufruf gelesen bzw. an
Borg/SSH als Pfad übergeben - nie als Prozessargument, nie im Log, nie in der API."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_HOST = re.compile(r"^[A-Za-z0-9.-]{1,253}$")
_USER = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_REPO_PATH = re.compile(r"^[A-Za-z0-9._/~-]{1,255}$")
_FINGERPRINT = re.compile(r"^SHA256:[A-Za-z0-9+/]{43}=?$")
_REMOTE_PATH = re.compile(r"^[A-Za-z0-9._/-]{1,128}$")
_COMPRESSION = re.compile(r"^(none|lz4|zstd(,\d{1,2})?|auto,(lz4|zstd(,\d{1,2})?))$")

GIB = 1024 ** 3


class BackupConfigError(ValueError):
    """Konfiguration unvollständig oder ungültig (erwartet, kuratierte Meldung)."""


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int, *, minimum: int = 0) -> int:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise BackupConfigError(f"{name} muss eine ganze Zahl sein") from exc
    if parsed < minimum:
        raise BackupConfigError(f"{name} muss mindestens {minimum} sein")
    return parsed


def _optional_path(name: str) -> Path | None:
    value = os.environ.get(name, "").strip()
    return Path(value) if value else None


@dataclass(frozen=True)
class BackupConfig:
    enabled: bool
    # Entweder Storage-Box-Felder (Produktion) oder eine vollständige Repository-URL (Tests,
    # lokales Borg-Repository, andere SSH-Ziele).
    host: str | None
    port: int
    user: str | None
    repository_path: str
    repository_url_override: str | None
    remote_path: str | None
    ssh_key_file: Path | None = field(repr=False)
    passphrase_file: Path | None = field(repr=False)
    known_hosts_file: Path | None
    host_fingerprint: str | None
    expected_repository_id: str | None
    maintenance_ssh_key_file: Path | None = field(repr=False)
    work_dir: Path
    staging_max_bytes: int
    batch_max_bytes: int
    batch_max_objects: int
    upload_ratelimit_kib: int
    lock_wait_seconds: int
    compression: str
    quota_bytes: int | None
    trust_filesystem_registry: bool
    pg_restore_jobs: int

    @property
    def repository_url(self) -> str:
        if self.repository_url_override:
            return self.repository_url_override
        if not self.host or not self.user:
            raise BackupConfigError("BACKUP_STORAGEBOX_HOST und BACKUP_STORAGEBOX_USER müssen gesetzt sein")
        path = self.repository_path
        # Hetzner: relative Pfade beziehen sich auf das Home der Storage Box ("./hocx").
        if not path.startswith(("/", "./", "~")):
            path = "./" + path
        return f"ssh://{self.user}@{self.host}:{self.port}/{path}"

    @property
    def is_remote(self) -> bool:
        return self.repository_url.startswith("ssh://")

    @property
    def staging_dir(self) -> Path:
        return self.work_dir / "staging"

    @property
    def borg_base_dir(self) -> Path:
        # Borg-Cache, Security-Verzeichnis (Repository-Pinning, Replay-Schutz) und Config -
        # muss über Neustarts erhalten bleiben (eigenes Volume).
        return self.work_dir / "borg"

    def public_summary(self) -> dict:
        """Für Admin-Anzeige und Logs - ohne Secrets und ohne Schlüsselpfade."""
        return {
            "enabled": self.enabled,
            "repository": self.redacted_repository(),
            "remote_path": self.remote_path,
            "host_key_pinned": bool(self.known_hosts_file or self.host_fingerprint),
            "repository_id_pinned": bool(self.expected_repository_id),
            "ssh_key_configured": bool(self.ssh_key_file),
            "passphrase_configured": bool(self.passphrase_file),
            "maintenance_key_present": bool(self.maintenance_ssh_key_file and self.maintenance_ssh_key_file.exists()),
            "staging_max_bytes": self.staging_max_bytes,
            "batch_max_bytes": self.batch_max_bytes,
            "upload_ratelimit_kib": self.upload_ratelimit_kib,
            "compression": self.compression,
            "quota_bytes": self.quota_bytes,
        }

    def redacted_repository(self) -> str:
        try:
            url = self.repository_url
        except BackupConfigError:
            return ""
        return url

    def validate(self, *, require_secrets: bool = True) -> None:
        if not self.repository_url_override:
            if not self.host or not _HOST.match(self.host):
                raise BackupConfigError("BACKUP_STORAGEBOX_HOST fehlt oder ist ungültig")
            if not self.user or not _USER.match(self.user):
                raise BackupConfigError("BACKUP_STORAGEBOX_USER fehlt oder ist ungültig")
            if not _REPO_PATH.match(self.repository_path) or ".." in self.repository_path.split("/"):
                raise BackupConfigError("BACKUP_REPOSITORY_PATH ist ungültig")
            if not 1 <= self.port <= 65535:
                raise BackupConfigError("BACKUP_STORAGEBOX_PORT ist ungültig")
        if self.remote_path and not _REMOTE_PATH.match(self.remote_path):
            raise BackupConfigError("BACKUP_REMOTE_PATH ist ungültig")
        if self.host_fingerprint and not _FINGERPRINT.match(self.host_fingerprint):
            raise BackupConfigError("BACKUP_SSH_HOST_FINGERPRINT muss die Form SHA256:... haben")
        if self.expected_repository_id and not _HEX64.match(self.expected_repository_id):
            raise BackupConfigError("BACKUP_REPOSITORY_ID muss 64 Hex-Zeichen enthalten")
        if not _COMPRESSION.match(self.compression):
            raise BackupConfigError("BACKUP_COMPRESSION ist ungültig")
        if require_secrets:
            if not self.passphrase_file or not self.passphrase_file.is_file():
                raise BackupConfigError("Borg-Passphrase fehlt (BACKUP_PASSPHRASE_FILE)")
            if self.is_remote:
                if not self.ssh_key_file or not self.ssh_key_file.is_file():
                    raise BackupConfigError("SSH-Schlüssel fehlt (BACKUP_SSH_KEY_FILE)")
                if not (self.known_hosts_file and self.known_hosts_file.is_file()) and not self.host_fingerprint:
                    # Nie unbekannte Host-Keys akzeptieren: ohne Pinning kein Verbindungsaufbau.
                    raise BackupConfigError("SSH-Host-Key nicht gepinnt (BACKUP_KNOWN_HOSTS_FILE oder BACKUP_SSH_HOST_FINGERPRINT)")


def load_config() -> BackupConfig:
    quota = _env_int("BACKUP_STORAGEBOX_QUOTA_BYTES", 0)
    config = BackupConfig(
        enabled=_env_bool("BACKUP_ENABLED", False),
        host=os.environ.get("BACKUP_STORAGEBOX_HOST", "").strip() or None,
        port=_env_int("BACKUP_STORAGEBOX_PORT", 23, minimum=1),
        user=os.environ.get("BACKUP_STORAGEBOX_USER", "").strip() or None,
        repository_path=os.environ.get("BACKUP_REPOSITORY_PATH", "hocx-borg").strip() or "hocx-borg",
        repository_url_override=os.environ.get("BACKUP_REPOSITORY_URL", "").strip() or None,
        remote_path=os.environ.get("BACKUP_REMOTE_PATH", "borg-1.4").strip() or None,
        ssh_key_file=_optional_path("BACKUP_SSH_KEY_FILE"),
        passphrase_file=_optional_path("BACKUP_PASSPHRASE_FILE"),
        known_hosts_file=_optional_path("BACKUP_KNOWN_HOSTS_FILE"),
        host_fingerprint=os.environ.get("BACKUP_SSH_HOST_FINGERPRINT", "").strip() or None,
        expected_repository_id=(os.environ.get("BACKUP_REPOSITORY_ID", "").strip().lower() or None),
        maintenance_ssh_key_file=_optional_path("BACKUP_MAINTENANCE_SSH_KEY_FILE"),
        work_dir=Path(os.environ.get("BACKUP_WORK_DIR", "/backup-work")),
        staging_max_bytes=_env_int("BACKUP_STAGING_MAX_BYTES", 20 * GIB, minimum=64 * 1024 * 1024),
        batch_max_bytes=_env_int("BACKUP_BATCH_MAX_BYTES", 2 * GIB, minimum=1024 * 1024),
        batch_max_objects=_env_int("BACKUP_BATCH_MAX_OBJECTS", 5000, minimum=1),
        upload_ratelimit_kib=_env_int("BACKUP_UPLOAD_RATELIMIT_KIB", 0),
        lock_wait_seconds=_env_int("BACKUP_LOCK_WAIT_SECONDS", 600, minimum=1),
        compression=os.environ.get("BACKUP_COMPRESSION", "auto,zstd,3").strip() or "auto,zstd,3",
        quota_bytes=quota or None,
        trust_filesystem_registry=_env_bool("BACKUP_TRUST_FILESYSTEM_REGISTRY", False),
        pg_restore_jobs=_env_int("BACKUP_PG_RESTORE_JOBS", 2, minimum=1),
    )
    config.validate(require_secrets=False)
    return config
