"""Isolierte Ausführung von Konvertierung, Parsern und OCR für nicht vertrauenswürdige Dokumente.

Jeder Aufruf ist ein eigener Kindprozess (eigene Prozessgruppe) mit
- Wanduhr-Timeout (danach SIGKILL an die ganze Prozessgruppe, auch an LibreOffice-Helfer),
- RLIMIT_CPU, RLIMIT_AS (Adressraum), RLIMIT_FSIZE (max. Dateigrösse), keine Core-Dumps,
- bereinigter Umgebung (keine DB-URLs, Secrets oder Speicher-Zugangsdaten) und
- einem eigenen, leeren Arbeitsordner, in dem nur die Eingabedatei liegt.

Mehr Isolation (eigener Netzwerk-Namespace, seccomp) bräuchte Container-Rechte; sie kommt deshalb
aus dem Deployment: der document-worker läuft read_only, ohne Capabilities, in einem Netz ohne
Internetzugang (docker-compose*.yml). Ausgaben des Kindprozesses werden nie mit Dokumentinhalt
protokolliert - nur gekürzte stderr-Zeilen für Fehlermeldungen."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

STDERR_LIMIT = 2000


class SandboxError(Exception):
    """Kindprozess ist fehlgeschlagen (Exit-Code != 0)."""


class SandboxTimeout(SandboxError):
    """Kindprozess hat das Zeitlimit überschritten und wurde beendet."""


@dataclass(frozen=True)
class Limits:
    timeout_seconds: float
    memory_bytes: int
    file_size_bytes: int = 512 * 1024 * 1024


def _preexec(limits: Limits):
    def apply() -> None:
        import resource

        cpu = int(limits.timeout_seconds) + 5
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
        resource.setrlimit(resource.RLIMIT_AS, (limits.memory_bytes, limits.memory_bytes))
        resource.setrlimit(resource.RLIMIT_FSIZE, (limits.file_size_bytes, limits.file_size_bytes))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    return apply


def minimal_env(work_dir: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin:/usr/lib/libreoffice/program",
        "HOME": str(work_dir),
        "TMPDIR": str(work_dir),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        # Kein Thread-Pool je CPU-Kern - der Worker hat ein festes CPU-Budget.
        "OMP_THREAD_LIMIT": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    if extra:
        env.update(extra)
    return env


def run(args: list[str], *, work_dir: Path, limits: Limits, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    process = subprocess.Popen(
        args,
        cwd=work_dir,
        env=env if env is not None else minimal_env(work_dir),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        preexec_fn=_preexec(limits) if sys.platform != "win32" else None,
        close_fds=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=limits.timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        _kill_group(process)
        process.communicate()
        raise SandboxTimeout(f"Zeitlimit von {int(limits.timeout_seconds)} s überschritten") from exc
    finally:
        # Hängengebliebene Helfer (z. B. oosplash) der Gruppe nie überleben lassen.
        _kill_group(process, only_if_alive=False)
    if process.returncode != 0:
        message = (stderr or b"").decode("utf-8", "replace").strip()[-STDERR_LIMIT:]
        raise SandboxError(f"Exit-Code {process.returncode}: {message}" if message else f"Exit-Code {process.returncode}")
    return subprocess.CompletedProcess(args, process.returncode, stdout, stderr)


def _kill_group(process: subprocess.Popen, *, only_if_alive: bool = True) -> None:
    if only_if_alive and process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def python_entry_args(*arguments: str) -> list[str]:
    """Aufruf von sandbox_entry.py im selben Interpreter im isolierten Modus (-I: keine
    Umgebungsvariablen PYTHON*, keine Benutzer-site-packages); den App-Pfad ergänzt das Skript
    selbst."""
    return [sys.executable, "-I", str(Path(__file__).with_name("sandbox_entry.py")), *arguments]
