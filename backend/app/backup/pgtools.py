"""PostgreSQL-Werkzeuge (pg_dump/pg_restore/psql) ohne Passwort in Prozessargumenten: die
Zugangsdaten landen in einer privaten .pgpass-Datei (0600), auf die PGPASSFILE zeigt."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

_DB_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


class PgToolError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class PgTarget:
    host: str
    port: int
    user: str
    password: str | None
    database: str

    @classmethod
    def from_url(cls, url: str) -> "PgTarget":
        """postgresql(+psycopg)://user:pass@host:port/db"""
        parts = urlsplit(url.replace("postgresql+psycopg://", "postgresql://", 1))
        if parts.scheme not in ("postgresql", "postgres") or not parts.hostname or not parts.path.strip("/"):
            raise PgToolError("invalid_url", "Datenbank-URL ist ungültig")
        return cls(
            host=parts.hostname, port=parts.port or 5432, user=unquote(parts.username or ""),
            password=unquote(parts.password) if parts.password else None, database=unquote(parts.path.strip("/")),
        )

    def with_database(self, database: str) -> "PgTarget":
        return PgTarget(self.host, self.port, self.user, self.password, validate_db_name(database))

    def sqlalchemy_url(self) -> str:
        from urllib.parse import quote

        auth = quote(self.user, safe="")
        if self.password is not None:
            auth += ":" + quote(self.password, safe="")
        return f"postgresql+psycopg://{auth}@{self.host}:{self.port}/{quote(self.database, safe='')}"


def validate_db_name(name: str) -> str:
    if not _DB_NAME.match(name or ""):
        raise PgToolError("invalid_name", "Ungültiger Datenbankname")
    return name


class PgTools:
    def __init__(self, target: PgTarget) -> None:
        self.target = target
        self._dir = Path(tempfile.mkdtemp(prefix="hocx-pg-"))
        os.chmod(self._dir, 0o700)
        passfile = self._dir / "pgpass"
        fd = os.open(passfile, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)

        def esc(value: str) -> str:
            return value.replace("\\", "\\\\").replace(":", "\\:")

        with os.fdopen(fd, "w") as handle:
            handle.write(f"{esc(target.host)}:{target.port}:*:{esc(target.user)}:{esc(target.password or '')}\n")
        self._env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "PGPASSFILE": str(passfile), "PGHOST": target.host,
            "PGPORT": str(target.port), "PGUSER": target.user, "PGCONNECT_TIMEOUT": "20", "LANG": "C.UTF-8",
            "PGAPPNAME": "hocx-backup",
        }

    def close(self) -> None:
        shutil.rmtree(self._dir, ignore_errors=True)

    def __enter__(self) -> "PgTools":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def _run(self, argv: list[str], *, timeout: float, input_bytes: bytes | None = None) -> subprocess.CompletedProcess:
        try:
            completed = subprocess.run(argv, env=self._env, capture_output=True, timeout=timeout, input=input_bytes, check=False)
        except FileNotFoundError as exc:
            raise PgToolError("tool_missing", f"{argv[0]} ist nicht installiert") from exc
        except subprocess.TimeoutExpired as exc:
            raise PgToolError("timeout", f"{argv[0]} hat das Zeitlimit überschritten") from exc
        if completed.returncode != 0:
            message = completed.stderr.decode("utf-8", errors="replace").strip().splitlines()
            raise PgToolError(f"{Path(argv[0]).name}_failed", (message[-1] if message else f"Exit-Code {completed.returncode}")[:500])
        return completed

    @staticmethod
    def client_major(tool: str = "pg_dump") -> int:
        output = subprocess.run([tool, "--version"], capture_output=True, timeout=30, check=False).stdout.decode()
        match = re.search(r"(\d+)(?:\.\d+)?", output)
        if not match:
            raise PgToolError("tool_missing", f"{tool} ist nicht installiert")
        return int(match.group(1))

    def dump(self, out: Path, *, snapshot: str | None = None, timeout: float = 12 * 3600) -> None:
        argv = ["pg_dump", "--format=custom", "--compress=6", "--no-sync", f"--file={out}", f"--dbname={self.target.database}"]
        if snapshot:
            if not re.match(r"^[0-9A-F-]{1,64}$", snapshot):
                raise PgToolError("invalid_snapshot", "Ungültige Snapshot-ID")
            argv.append(f"--snapshot={snapshot}")
        self._run(argv, timeout=timeout)

    def dump_globals(self, out: Path) -> bool:
        """Rollen ohne Passwörter (die setzt das Deployment aus den Secrets). Optional - ohne
        Superuser-Recht nur eine Warnung."""
        try:
            completed = self._run(["pg_dumpall", "--roles-only", "--no-role-passwords", f"--dbname={self.target.database}"], timeout=600)
        except PgToolError:
            return False
        out.write_bytes(completed.stdout)
        return True

    def list_dump(self, path: Path) -> list[str]:
        completed = self._run(["pg_restore", "--list", str(path)], timeout=1800)
        return [line for line in completed.stdout.decode("utf-8", errors="replace").splitlines() if line and not line.startswith(";")]

    def psql(self, sql: str, *, database: str | None = None, timeout: float = 600) -> str:
        completed = self._run(
            ["psql", "-X", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1", f"--dbname={database or self.target.database}"],
            timeout=timeout, input_bytes=sql.encode(),
        )
        return completed.stdout.decode("utf-8", errors="replace").strip()

    def create_database(self, name: str, *, owner: str | None = None) -> None:
        validate_db_name(name)
        owner_sql = f' OWNER "{validate_db_name(owner)}"' if owner else ""
        self.psql(f'CREATE DATABASE "{name}"{owner_sql} TEMPLATE template0;', database="postgres")

    def drop_database(self, name: str) -> None:
        validate_db_name(name)
        if name == self.target.database:
            raise PgToolError("refused", "Die Ausgangsdatenbank wird nie gelöscht")
        self.psql(
            f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{name}' AND pid <> pg_backend_pid();\n"
            f'DROP DATABASE IF EXISTS "{name}";', database="postgres",
        )

    def database_exists(self, name: str) -> bool:
        validate_db_name(name)
        return self.psql(f"SELECT 1 FROM pg_database WHERE datname = '{name}';", database="postgres") == "1"

    def restore(self, dump: Path, database: str, *, jobs: int = 2, no_owner: bool = False, timeout: float = 24 * 3600) -> None:
        argv = ["pg_restore", "--exit-on-error", f"--jobs={max(1, jobs)}", f"--dbname={validate_db_name(database)}"]
        if no_owner:
            argv += ["--no-owner", "--no-privileges"]
        argv.append(str(dump))
        self._run(argv, timeout=timeout)
