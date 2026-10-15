"""Schmale, sichere Hülle um das borg-1.4-CLI.

- Aufrufe immer als Argumentliste (nie Shell), Archivnamen/Pfade werden vorher geprüft.
- Passphrase nur über BORG_PASSCOMMAND (liest die Secret-Datei), SSH-Schlüssel und known_hosts
  nur als Pfad im BORG_RSH - nichts davon steht in Prozessargumenten oder Logs.
- Host-Keys werden nie automatisch akzeptiert (StrictHostKeyChecking=yes, eigene known_hosts).
- Fehler kommen maschinenlesbar (--log-json) und werden auf stabile Codes abgebildet
  (BorgError.code), die Worker, API und ntfy weiterverwenden.

Verhalten, auf das sich der Worker verlässt (mit borg 1.4.0 verifiziert, siehe
tests/test_backup_borg.py): ein per SIGTERM abgebrochenes oder mit unvollständigem Tar-Stream
beendetes `borg import-tar` legt KEIN Archiv an; `borg recreate --exclude` ändert die
Archiv-ID; `borg delete` nimmt mehrere Archivnamen.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shlex
import shutil
import signal
import subprocess
import tarfile
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any

from app.backup.config import BackupConfig, BackupConfigError, secret_file_present

_logger = logging.getLogger("hocx.backup.borg")

ARCHIVE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
# Pfade innerhalb unserer Archive - nur das, was der Worker selbst schreibt.
ARCHIVE_PATH = re.compile(r"^(pool/[0-9a-f]{2}/[0-9a-f]{64}|hocx-backup\.json|manifest\.jsonl\.gz|db/[a-z0-9_.-]{1,64}|recovery/[A-Za-z0-9_.-]{1,64})$")
_STDERR_LIMIT = 200
_DEFAULT_TIMEOUT = 6 * 3600

_MSGID_CODES = {
    "PassphraseWrong": "passphrase_wrong",
    "Repository.DoesNotExist": "repository_missing",
    "Repository.InvalidRepository": "repository_invalid",
    "Repository.InvalidRepositoryConfig": "repository_invalid",
    "Repository.AlreadyExists": "repository_exists",
    "Repository.CheckNeeded": "check_needed",
    "Repository.InsufficientFreeSpaceError": "insufficient_space",
    "Repository.StorageQuotaExceeded": "quota_exceeded",
    "Repository.ObjectNotFound": "repository_damaged",
    "IntegrityError": "repository_damaged",
    "LockTimeout": "lock_timeout",
    "LockFailed": "lock_timeout",
    "LockError": "lock_timeout",
    "ConnectionClosed": "connection_lost",
    "ConnectionClosedWithHint": "connection_lost",
    "Archive.AlreadyExists": "archive_exists",
    "Archive.DoesNotExist": "archive_missing",
    "Cache.RepositoryReplay": "repository_replay",
    "Cache.RepositoryAccessAborted": "repository_relocated",
    "Cache.RepositoryIDNotUnique": "repository_invalid",
    "Cache.EncryptionMethodMismatch": "repository_replay",
    "UnsupportedPayloadError": "repository_damaged",
    "UnsupportedManifestError": "version_mismatch",
    "InvalidPlaceholder": "borg_error",
}
_SSH_PATTERNS = (
    (re.compile(r"Host key verification failed|REMOTE HOST IDENTIFICATION HAS CHANGED|No .* host key is known"), "host_key_mismatch"),
    (re.compile(r"Permission denied \(publickey"), "ssh_auth_failed"),
    (re.compile(r"Connection refused|Connection timed out|Could not resolve hostname|No route to host|Network is unreachable|Connection reset"), "repository_unreachable"),
)
# Codes, bei denen ein späterer neuer Versuch sinnvoll ist.
TRANSIENT_CODES = {"repository_unreachable", "connection_lost", "lock_timeout"}


class BorgError(Exception):
    def __init__(self, code: str, message: str, *, rc: int | None = None, msgids: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.code = code
        self.rc = rc
        self.msgids = msgids

    @property
    def transient(self) -> bool:
        return self.code in TRANSIENT_CODES


@dataclass
class BorgResult:
    rc: int
    stdout: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    raw_stderr: list[str] = field(default_factory=list)

    @property
    def warnings(self) -> list[str]:
        return [m.get("message", "") for m in self.messages if m.get("levelname") == "WARNING"]


def validate_archive_name(name: str) -> str:
    if not isinstance(name, str) or not ARCHIVE_NAME.match(name):
        raise BorgError("invalid_argument", "Ungültiger Archivname")
    return name


def validate_archive_path(path: str) -> str:
    if not isinstance(path, str) or not ARCHIVE_PATH.match(path):
        raise BorgError("invalid_argument", "Ungültiger Pfad im Archiv")
    return path


def _parse_stderr(lines: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    messages: list[dict[str, Any]] = []
    raw: list[str] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("{"):
            try:
                item = json.loads(line)
            except ValueError:
                raw.append(line[:500])
                continue
            if item.get("type") == "log_message":
                messages.append({k: item.get(k) for k in ("levelname", "msgid", "message", "name")})
            continue
        raw.append(line[:500])
    return messages[-_STDERR_LIMIT:], raw[-_STDERR_LIMIT:]


def classify(rc: int, messages: list[dict[str, Any]], raw: list[str]) -> BorgError:
    msgids = tuple(m["msgid"] for m in messages if m.get("msgid"))
    code = "borg_error"
    # SSH-Meldungen zuerst: borg meldet einen abgewiesenen Host-Key nur als ConnectionClosed,
    # die eigentliche Ursache steht in der (Remote-)Ausgabe von ssh.
    text = "\n".join(raw + [str(m.get("message") or "") for m in messages])
    for pattern, ssh_code in _SSH_PATTERNS:
        if pattern.search(text):
            code = ssh_code
            break
    else:
        for msgid in msgids:
            if msgid in _MSGID_CODES:
                code = _MSGID_CODES[msgid]
                break
        else:
            if rc < 0 or rc >= 128:
                code = "interrupted"
    errors = [str(m.get("message") or "") for m in messages if m.get("levelname") in ("ERROR", "CRITICAL")]
    detail = (errors[-1] if errors else (raw[-1] if raw else f"borg beendet mit Code {rc}"))[:500]
    return BorgError(code, detail, rc=rc, msgids=msgids)


class _StderrCollector(threading.Thread):
    def __init__(self, stream: IO[bytes]) -> None:
        super().__init__(daemon=True)
        self.stream = stream
        self.lines: list[str] = []

    def run(self) -> None:
        for line in iter(self.stream.readline, b""):
            self.lines.append(line.decode("utf-8", errors="replace"))
            if len(self.lines) > 5000:
                del self.lines[:1000]


class Borg:
    """Ein Borg-Zugang (Backup- oder Wartungsschlüssel). runtime_dir nimmt private Kopien von
    SSH-Schlüssel und known_hosts auf (0600) - ssh verweigert zu offene Schlüsseldateien, und
    Docker-Secrets haben die Rechte des Hosts."""

    def __init__(self, config: BackupConfig, *, ssh_key_file: Path | None = None, binary: str = "borg") -> None:
        self.config = config
        self.binary = binary
        self._ssh_key_source = ssh_key_file if ssh_key_file is not None else config.ssh_key_file
        self._runtime_dir: Path | None = None
        self._rsh: str | None = None
        self._lock = threading.Lock()

    # --- Umgebung -----------------------------------------------------------------------------

    def _runtime(self) -> Path:
        if self._runtime_dir is None:
            self._runtime_dir = Path(tempfile.mkdtemp(prefix="hocx-borg-"))
            os.chmod(self._runtime_dir, 0o700)
        return self._runtime_dir

    def close(self) -> None:
        if self._runtime_dir is not None:
            shutil.rmtree(self._runtime_dir, ignore_errors=True)
            self._runtime_dir = None
            self._rsh = None

    def _private_copy(self, source: Path, name: str) -> Path:
        target = self._runtime() / name
        data = source.read_bytes()
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data if data.endswith(b"\n") else data + b"\n")
        return target

    def _known_hosts(self) -> Path:
        config = self.config
        if secret_file_present(config.known_hosts_file):
            return self._private_copy(config.known_hosts_file, "known_hosts")
        if not config.host_fingerprint:
            raise BackupConfigError("SSH-Host-Key nicht gepinnt")
        return self._known_hosts_from_fingerprint()

    def _known_hosts_from_fingerprint(self) -> Path:
        """Holt die Host-Keys per ssh-keyscan und übernimmt NUR den Schlüssel, dessen
        SHA256-Fingerprint dem konfigurierten entspricht. Passt keiner: Abbruch."""
        config = self.config
        scan = subprocess.run(
            ["ssh-keyscan", "-T", "15", "-p", str(config.port), config.host or ""],
            capture_output=True, timeout=60, check=False,
        )
        accepted: list[str] = []
        for line in scan.stdout.decode("utf-8", errors="replace").splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            fingerprint = subprocess.run(["ssh-keygen", "-lf", "-"], input=(line + "\n").encode(), capture_output=True, timeout=30, check=False)
            parts = fingerprint.stdout.decode().split()
            if len(parts) >= 2 and parts[1] == config.host_fingerprint:
                accepted.append(line)
        if not accepted:
            raise BorgError("host_key_mismatch", "Kein Host-Key der Storage Box passt zum konfigurierten Fingerprint")
        target = self._runtime() / "known_hosts"
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write("\n".join(accepted) + "\n")
        return target

    def _borg_rsh(self) -> str:
        with self._lock:
            if self._rsh is None:
                if not secret_file_present(self._ssh_key_source):
                    raise BackupConfigError("SSH-Schlüssel fehlt")
                key = self._private_copy(self._ssh_key_source, "id_backup")
                known_hosts = self._known_hosts()
                options = [
                    "ssh", "-F", "/dev/null", "-i", str(key),
                    "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
                    "-o", "StrictHostKeyChecking=yes", "-o", f"UserKnownHostsFile={known_hosts}",
                    "-o", "GlobalKnownHostsFile=/dev/null", "-o", "PasswordAuthentication=no",
                    "-o", "KbdInteractiveAuthentication=no", "-o", "ConnectTimeout=20",
                    "-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=6",
                ]
                self._rsh = " ".join(shlex.quote(part) for part in options)
            return self._rsh

    def env(self) -> dict[str, str]:
        config = self.config
        base = config.borg_base_dir
        base.mkdir(parents=True, exist_ok=True)
        env = {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "HOME": str(base),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "TMPDIR": str(self._runtime()),
            "BORG_REPO": config.repository_url,
            "BORG_BASE_DIR": str(base),
            "BORG_EXIT_CODES": "legacy",
            "BORG_HOSTNAME_IS_UNIQUE": "yes",
            "BORG_RELOCATED_REPO_ACCESS_IS_OK": "no",
            "BORG_UNKNOWN_UNENCRYPTED_REPO_ACCESS_IS_OK": "no",
            "BORG_CHECK_I_KNOW_WHAT_I_AM_DOING": "NO",
            "BORG_DELETE_I_KNOW_WHAT_I_AM_DOING": "NO",
            "BORG_DISPLAY_PASSPHRASE": "no",
            "BORG_RECREATE_I_KNOW_WHAT_I_AM_DOING": "YES",
        }
        if config.passphrase_file:
            env["BORG_PASSCOMMAND"] = f"cat {shlex.quote(str(config.passphrase_file))}"
        if config.is_remote:
            env["BORG_RSH"] = self._borg_rsh()
        return env

    def _argv(self, command: list[str], *extra: str) -> list[str]:
        argv = [self.binary, *command, "--log-json", "--lock-wait", str(self.config.lock_wait_seconds)]
        if self.config.is_remote and self.config.remote_path:
            argv += ["--remote-path", self.config.remote_path]
        argv += list(extra)
        return argv

    # --- Ausführung ---------------------------------------------------------------------------

    def run(self, command: list[str], *extra: str, timeout: float = _DEFAULT_TIMEOUT, input_bytes: bytes | None = None,
            allow_warning: bool = True) -> BorgResult:
        argv = self._argv(command, *extra)
        try:
            completed = subprocess.run(argv, input=input_bytes, capture_output=True, env=self.env(), timeout=timeout, check=False)
        except subprocess.TimeoutExpired as exc:
            raise BorgError("timeout", f"borg {command[0]} hat das Zeitlimit überschritten") from exc
        except FileNotFoundError as exc:
            raise BorgError("borg_missing", "borg ist nicht installiert") from exc
        messages, raw = _parse_stderr(completed.stderr.decode("utf-8", errors="replace").splitlines())
        result = BorgResult(rc=completed.returncode, stdout=completed.stdout.decode("utf-8", errors="replace"), messages=messages, raw_stderr=raw)
        if completed.returncode == 0 or (completed.returncode == 1 and allow_warning):
            return result
        raise classify(completed.returncode, messages, raw)

    def _popen(self, command: list[str], *extra: str, stdin: bool = False) -> tuple[subprocess.Popen, _StderrCollector]:
        try:
            process = subprocess.Popen(
                self._argv(command, *extra), stdin=subprocess.PIPE if stdin else subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env(),
            )
        except FileNotFoundError as exc:
            raise BorgError("borg_missing", "borg ist nicht installiert") from exc
        collector = _StderrCollector(process.stderr)  # type: ignore[arg-type]
        collector.start()
        return process, collector

    @staticmethod
    def _finish(process: subprocess.Popen, collector: _StderrCollector, *, timeout: float = 600) -> BorgResult:
        try:
            rc = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            rc = process.wait()
        collector.join(timeout=10)
        messages, raw = _parse_stderr(collector.lines)
        if rc not in (0, 1):
            raise classify(rc, messages, raw)
        return BorgResult(rc=rc, stdout="", messages=messages, raw_stderr=raw)

    # --- Befehle ------------------------------------------------------------------------------

    def version(self) -> str:
        completed = subprocess.run([self.binary, "--version"], capture_output=True, timeout=30, check=False)
        return completed.stdout.decode().strip()

    def repo_info(self) -> dict[str, Any]:
        return json.loads(self.run(["info", "--json"], "::", timeout=1800).stdout)

    def list_archives(self, *, glob: str | None = None) -> list[dict[str, Any]]:
        extra = ["--json"] + (["--glob-archives", glob] if glob else [])
        data = json.loads(self.run(["list"], *extra, "::", timeout=1800).stdout)
        return [{"name": a["name"], "id": a["id"], "start": a.get("start") or a.get("time")} for a in data.get("archives", [])]

    def archive_info(self, archive: str) -> dict[str, Any]:
        data = json.loads(self.run(["info", "--json"], f"::{validate_archive_name(archive)}", timeout=1800).stdout)
        return data["archives"][0]

    def iter_items(self, archive: str) -> Iterator[dict[str, Any]]:
        """Inhalt eines Archivs, gestreamt (Pool-Archive können sehr viele Einträge haben)."""
        process, collector = self._popen(["list", "--json-lines"], f"::{validate_archive_name(archive)}")
        assert process.stdout is not None
        try:
            for line in process.stdout:
                if line.strip():
                    item = json.loads(line)
                    yield {"path": item.get("path"), "size": item.get("size"), "type": item.get("type")}
        except BaseException:
            process.kill()
            raise
        self._finish(process, collector)

    @contextmanager
    def extract_stream(self, archive: str, path: str) -> Iterator[IO[bytes]]:
        """Liefert den Inhalt einer Datei aus dem Archiv als Stream (borg extract --stdout)."""
        process, collector = self._popen(["extract", "--stdout"], f"::{validate_archive_name(archive)}", validate_archive_path(path))
        assert process.stdout is not None
        try:
            yield process.stdout
        except BaseException:
            process.kill()
            process.wait()
            raise
        else:
            # Rest lesen, damit borg nicht an einer vollen Pipe hängt.
            process.stdout.read()
            self._finish(process, collector)

    @contextmanager
    def export_tar(self, archive: str, paths: list[str]) -> Iterator[tarfile.TarFile]:
        """Mehrere Dateien eines Archivs in EINEM borg-Aufruf als Tar-Stream - für Restores mit
        vielen Objekten (ein Aufruf pro Datei wäre um Grössenordnungen langsamer)."""
        patterns = self._runtime() / f"patterns-{os.getpid()}-{threading.get_ident()}"
        with patterns.open("w", encoding="utf-8") as handle:
            for path in paths:
                handle.write(f"+ pp:{validate_archive_path(path)}\n")
            handle.write("- fm:*\n")
        process, collector = self._popen(["export-tar", "--patterns-from", str(patterns)], f"::{validate_archive_name(archive)}", "-")
        assert process.stdout is not None
        try:
            with tarfile.open(fileobj=process.stdout, mode="r|") as stream:
                yield stream
            process.stdout.read()
        except BaseException:
            process.kill()
            process.wait()
            raise
        finally:
            patterns.unlink(missing_ok=True)
        self._finish(process, collector)

    def import_tar(self, archive: str, *, comment: str | None = None) -> "ImportTarProcess":
        extra = ["--json", "--compression", self.config.compression]
        if self.config.upload_ratelimit_kib:
            extra += ["--upload-ratelimit", str(self.config.upload_ratelimit_kib)]
        if comment:
            extra += ["--comment", comment[:200]]
        process, collector = self._popen(["import-tar", *extra], f"::{validate_archive_name(archive)}", "-", stdin=True)
        return ImportTarProcess(process, collector)

    def delete_archives(self, names: list[str]) -> None:
        if not names:
            return
        for start in range(0, len(names), 50):
            chunk = [validate_archive_name(name) for name in names[start:start + 50]]
            self.run(["delete"], "::", *chunk, timeout=6 * 3600)

    def recreate_exclude(self, archive: str, paths: list[str]) -> None:
        """Entfernt Pfade aus einem Archiv (nur Metadaten; Chunks bleiben bis compact)."""
        patterns = self._runtime() / f"exclude-{os.getpid()}-{threading.get_ident()}"
        with patterns.open("w", encoding="utf-8") as handle:
            for path in paths:
                handle.write(f"- pp:{validate_archive_path(path)}\n")
        try:
            self.run(["recreate", "--patterns-from", str(patterns)], f"::{validate_archive_name(archive)}", timeout=12 * 3600)
        finally:
            patterns.unlink(missing_ok=True)

    def rename(self, archive: str, new_name: str) -> None:
        self.run(["rename"], f"::{validate_archive_name(archive)}", validate_archive_name(new_name), timeout=1800)

    def check(self, *, repository_only: bool = False, archives_only: bool = False, verify_data: bool = False,
              glob: str | None = None, timeout: float = 24 * 3600) -> BorgResult:
        extra: list[str] = []
        if repository_only:
            extra.append("--repository-only")
        if archives_only:
            extra.append("--archives-only")
        if verify_data:
            extra.append("--verify-data")
        if glob:
            extra += ["--glob-archives", glob]
        return self.run(["check"], *extra, "::", timeout=timeout, allow_warning=False)

    def init(self, *, encryption: str = "repokey-blake2") -> BorgResult:
        if encryption not in ("repokey-blake2", "repokey"):
            raise BorgError("invalid_argument", "Nur authentifizierte repokey-Verschlüsselung ist zulässig")
        return self.run(["init", "--encryption", encryption, "--make-parent-dirs"], "::", timeout=1800)

    def key_export(self, target: Path, *, paper: bool = False) -> None:
        extra = ["--paper"] if paper else []
        self.run(["key", "export", *extra], "::", str(target), timeout=600)

    def compact(self) -> BorgResult:
        return self.run(["compact", "--cleanup-commits"], "::", timeout=24 * 3600)

    def break_lock(self) -> None:
        self.run(["break-lock"], "::", timeout=600)


class ImportTarProcess:
    """Laufendes `borg import-tar` mit stdin als Tar-Ziel. finish() schliesst den Stream und
    liefert die Archiv-Statistik; abort() bricht ab, ohne dass ein Archiv entsteht."""

    def __init__(self, process: subprocess.Popen, collector: _StderrCollector) -> None:
        self.process = process
        self.collector = collector
        self._stdout: list[bytes] = []
        self._reader = threading.Thread(target=self._read_stdout, daemon=True)
        self._reader.start()

    def _read_stdout(self) -> None:
        assert self.process.stdout is not None
        self._stdout.append(self.process.stdout.read())

    @property
    def stdin(self) -> IO[bytes]:
        assert self.process.stdin is not None
        return self.process.stdin

    def alive(self) -> bool:
        return self.process.poll() is None

    def failure(self) -> BorgError:
        """Fehler, nachdem borg vorzeitig beendet hat (z. B. Broken Pipe beim Schreiben)."""
        rc = self.process.wait(timeout=600)
        self.collector.join(timeout=10)
        messages, raw = _parse_stderr(self.collector.lines)
        return classify(rc if rc not in (0, 1) else 2, messages, raw)

    def finish(self, *, timeout: float = 6 * 3600) -> dict[str, Any]:
        try:
            self.stdin.close()
        except BrokenPipeError:
            pass
        try:
            rc = self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            self.abort()
            raise BorgError("timeout", "borg import-tar hat das Zeitlimit überschritten") from exc
        self._reader.join(timeout=30)
        self.collector.join(timeout=10)
        messages, raw = _parse_stderr(self.collector.lines)
        if rc not in (0, 1):
            raise classify(rc, messages, raw)
        output = b"".join(self._stdout).decode("utf-8", errors="replace")
        try:
            return json.loads(output)
        except ValueError as exc:
            raise BorgError("borg_error", "borg import-tar lieferte keine Statistik") from exc

    def abort(self) -> None:
        if self.process.poll() is None:
            self.process.send_signal(signal.SIGTERM)
        try:
            self.stdin.close()
        except (BrokenPipeError, ValueError, OSError):
            pass
        try:
            self.process.wait(timeout=120)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        self.collector.join(timeout=10)
