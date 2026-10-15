"""Bausteine der Wiederherstellung - gemeinsam für den Admin-Restore (Worker), den automatischen
Restore-Test und die unabhängige Recovery-CLI. Kein Zugriff auf die laufende hocX-Datenbank:
Ziele werden immer explizit übergeben (Datenbank-URL, Backend des Ziel-Speichers).

Grundsätze:
- Datenbank immer in eine NEUE, leere Datenbank wiederherstellen (nie über eine bestehende).
- Objekte immer in eine NEUE Generation des Zielprofils schreiben (eigener Präfix g<n>/) - die
  bisherigen Daten bleiben unangetastet, ein altes Profil wird nie blind aktiviert.
- Jeder Inhalt wird beim Lesen aus Borg gegen den SHA-256 des Manifests geprüft und beim
  Schreiben ins Ziel erneut (put_stream_unbuffered).
"""

from __future__ import annotations

import io
import logging
import os
import subprocess
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from app.backup.manifest import DUMP_PATH, ManifestEntry, parse_rp_name
from app.backup.pgtools import PgTools, validate_db_name
from app.backup.repository import FetchReport, RepositoryView
from app.core.objstore_client import Backend, ObjectInfo, StorageError

_logger = logging.getLogger("hocx.backup.restore")
BACKEND_ROOT = Path(__file__).resolve().parents[2]
SLICE = 200_000


class RestoreError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# --- Sicherungspunkt ----------------------------------------------------------------------


def load_restore_point(view: RepositoryView, archive: str) -> dict[str, Any]:
    parsed = parse_rp_name(archive)
    if parsed is None or parsed[2]:
        raise RestoreError("invalid_archive", "Kein gültiger Wiederherstellungspunkt")
    metadata = view.read_metadata(archive)
    if metadata.get("backup_id") != str(parsed[1]):
        raise RestoreError("metadata_mismatch", "Metadaten passen nicht zum Archivnamen")
    return metadata


def schema_compatibility(revision: str | None) -> dict[str, Any]:
    """same: Datenbank passt zum Code; upgrade: ältere Revision, kontrolliertes Alembic-Upgrade
    nach der Prüfung möglich; newer/unknown: dieser Code kann den Stand nicht sicher betreiben -
    dafür die passende hocX-Version einspielen."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(str(BACKEND_ROOT / "alembic.ini")))
    head = script.get_current_head()
    if revision is None:
        return {"state": "unknown", "head": head, "revision": None}
    if revision == head:
        return {"state": "same", "head": head, "revision": revision}
    try:
        known = script.get_revision(revision)
    except Exception:  # noqa: BLE001 - unbekannte Revision
        known = None
    if known is None:
        return {"state": "newer", "head": head, "revision": revision}
    return {"state": "upgrade", "head": head, "revision": revision}


def run_alembic_upgrade(database_url: str, *, timeout: float = 3600) -> None:
    env = dict(os.environ)
    env["DATABASE_URL"] = database_url
    env.pop("DATABASE_URL_FILE", None)
    completed = subprocess.run(["alembic", "upgrade", "head"], cwd=str(BACKEND_ROOT), env=env, capture_output=True, timeout=timeout, check=False)
    if completed.returncode != 0:
        tail = completed.stderr.decode("utf-8", errors="replace").strip().splitlines()[-5:]
        raise RestoreError("alembic_failed", "Alembic-Upgrade fehlgeschlagen: " + " | ".join(tail)[:800])


# --- Datenbank ----------------------------------------------------------------------------


def restore_database(view: RepositoryView, archive: str, metadata: dict[str, Any], pg: PgTools, db_name: str, work_dir: Path, *,
                     max_bytes: int, jobs: int = 2, owner: str | None = None, no_owner: bool = False) -> dict[str, Any]:
    validate_db_name(db_name)
    if pg.database_exists(db_name):
        raise RestoreError("target_exists", f"Zieldatenbank {db_name} existiert bereits - Restore nur in eine neue Datenbank")
    work_dir.mkdir(parents=True, exist_ok=True)
    dump = work_dir / f"restore-{uuid.uuid4().hex}.pgdump"
    try:
        _, size = view.download(archive, DUMP_PATH, dump, expected_sha256=metadata["db_dump_sha256"], max_bytes=max_bytes)
        toc = pg.list_dump(dump)
        if not any("TABLE DATA public alembic_version" in line for line in toc):
            raise RestoreError("dump_invalid", "Dump enthält keine alembic_version")
        pg.create_database(db_name, owner=owner)
        pg.restore(dump, db_name, jobs=jobs, no_owner=no_owner)
    finally:
        dump.unlink(missing_ok=True)
    return {"dump_bytes": size, "toc_entries": len(toc)}


# --- Objekte ------------------------------------------------------------------------------


class _ChunkReader(io.RawIOBase):
    def __init__(self, chunks: Iterator[bytes]) -> None:
        self._chunks = chunks
        self._buffer = b""

    def readable(self) -> bool:
        return True

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            data = self._buffer + b"".join(self._chunks)
            self._buffer = b""
            return data
        while len(self._buffer) < size:
            chunk = next(self._chunks, b"")
            if not chunk:
                break
            self._buffer += chunk
        data, self._buffer = self._buffer[:size], self._buffer[size:]
        return data

    def readinto(self, buffer) -> int:
        data = self.read(len(buffer))
        buffer[: len(data)] = data
        return len(data)


def iter_manifest_slices(view: RepositoryView, archive: str, metadata: dict[str, Any], work_dir: Path,
                         *, keep: Callable[[ManifestEntry], bool] | None = None, size: int = SLICE) -> Iterator[list[ManifestEntry]]:
    with view.open_manifest(archive, work_dir, expected_sha256=metadata["manifest_sha256"]) as (_, entries):
        current: list[ManifestEntry] = []
        for entry in entries:
            if keep is not None and not keep(entry):
                continue
            current.append(entry)
            if len(current) >= size:
                yield current
                current = []
        if current:
            yield current


def write_contents_sink(backend: Backend, *, key_for: Callable[[ManifestEntry], tuple[str, str]] | None = None,
                        written: list[tuple[str, str]] | None = None) -> Callable[[str, int, Iterator[bytes], list[ManifestEntry]], None]:
    """Sink für RepositoryView.fetch_contents: schreibt den Inhalt unter dem ersten Ziel-Key und
    kopiert ihn für weitere Keys mit demselben Inhalt (serverseitig bzw. erneut gestreamt)."""

    def sink(sha: str, size: int, chunks: Iterator[bytes], targets: list[ManifestEntry]) -> None:
        resolved = [key_for(t) if key_for else (t.namespace, t.key) for t in targets]
        first_ns, first_key = resolved[0]
        backend.put_stream_unbuffered(first_ns, first_key, _ChunkReader(chunks), size=size, sha256=sha, content_type=None)
        if written is not None:
            written.append((first_ns, first_key))
        for namespace, key in resolved[1:]:
            if (namespace, key) == (first_ns, first_key):
                continue
            if namespace == first_ns:
                backend.copy(namespace, first_key, key)
            else:
                backend.put_stream_unbuffered(namespace, key, _ChunkReader(backend.open_read(first_ns, first_key)), size=size, sha256=sha, content_type=None)
            if written is not None:
                written.append((namespace, key))

    return sink


def restore_objects(view: RepositoryView, archive: str, metadata: dict[str, Any], backend: Backend, work_dir: Path, *,
                    should_stop: Callable[[], None] | None = None, progress: Callable[[dict[str, Any]], None] | None = None,
                    skip_existing: bool = False) -> dict[str, Any]:
    total = FetchReport()
    expected = int(metadata.get("object_count") or 0)
    skipped = 0
    for chunk in iter_manifest_slices(view, archive, metadata, work_dir):
        if skip_existing:
            remaining = []
            for entry in chunk:
                info = backend.head(entry.namespace, entry.key)
                if info is not None and info.size == entry.size and info.sha256 == entry.sha256:
                    skipped += 1
                    continue
                remaining.append(entry)
            chunk = remaining
        report = view.fetch_contents(chunk, write_contents_sink(backend), should_stop=should_stop)
        total.fetched += report.fetched
        total.fetched_bytes += report.fetched_bytes
        total.missing += report.missing
        total.corrupt += report.corrupt
        if progress is not None:
            progress({"objects_total": expected, "contents_restored": total.fetched, "bytes_restored": total.fetched_bytes,
                      "skipped": skipped, "missing": len(total.missing), "corrupt": len(total.corrupt)})
    return {"contents_restored": total.fetched, "bytes_restored": total.fetched_bytes, "skipped_existing": skipped,
            "missing": total.missing[:200], "missing_count": len(total.missing), "corrupt": total.corrupt[:200],
            "corrupt_count": len(total.corrupt), "ok": total.ok}


def verify_stream(view: RepositoryView, archive: str, metadata: dict[str, Any], work_dir: Path, *,
                  keep: Callable[[ManifestEntry], bool] | None = None, should_stop: Callable[[], None] | None = None,
                  progress: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
    """Liest Inhalte aus dem Repository und prüft SHA-256/Grösse, ohne sie zu speichern
    (Integritätsprüfung, Restore-Test ohne Speicherverbrauch)."""
    total = FetchReport()
    checked_entries = 0

    def discard(_sha: str, _size: int, chunks: Iterator[bytes], _targets: list[ManifestEntry]) -> None:
        for _ in chunks:
            pass

    for chunk in iter_manifest_slices(view, archive, metadata, work_dir, keep=keep):
        checked_entries += len(chunk)
        report = view.fetch_contents(chunk, discard, should_stop=should_stop)
        total.fetched += report.fetched
        total.fetched_bytes += report.fetched_bytes
        total.missing += report.missing
        total.corrupt += report.corrupt
        if progress is not None:
            progress({"entries_checked": checked_entries, "contents_checked": total.fetched, "bytes_checked": total.fetched_bytes})
    return {"entries_checked": checked_entries, "contents_checked": total.fetched, "bytes_checked": total.fetched_bytes,
            "missing": total.missing[:200], "missing_count": len(total.missing), "corrupt": total.corrupt[:200],
            "corrupt_count": len(total.corrupt), "ok": total.ok}


def ensure_empty_generation(backend: Backend) -> None:
    """Die neue Generation darf noch keine Objekte enthalten (Schutz vor Generationskollision)."""
    for namespace in ("main", "abgabebox"):
        for info in backend.list(namespace, ""):
            raise RestoreError("generation_not_empty", f"Ziel-Generation {backend.config.generation} enthält bereits Objekte ({namespace}/{info.key})")


def purge_generation_objects(backend: Backend) -> int:
    removed = 0
    for namespace in ("main", "abgabebox"):
        for info in list(backend.list(namespace, "")):
            backend.delete(namespace, info.key)
            removed += 1
    return removed


# --- Wiederhergestellte Datenbank konfigurieren ------------------------------------------


PROFILE_COLUMNS = (
    "provider", "endpoint_url", "region", "bucket", "abgabebox_bucket", "prefix", "addressing_style", "access_key_enc",
    "secret_key_enc", "restricted_access_key_enc", "restricted_secret_key_enc", "tls_verify", "ca_bundle_pem",
)


def configure_restored_database(database_url: str, *, profile: dict[str, Any], generation: int, fallback_days: int = 14,
                                note: str = "restore") -> dict[str, Any]:
    """Setzt in der wiederhergestellten Datenbank den Speicher auf die neue Generation des
    Zielprofils und räumt Zustände auf, die nur zur alten Umgebung gehörten (offene Migrationen,
    Storage-Wartungsfenster, Backup-Hold). profile enthält die Spalten aus PROFILE_COLUMNS
    (Zugangsdaten bereits mit STORAGE_CREDENTIALS_KEY verschlüsselt) plus public_id und name."""
    engine = create_engine(database_url, poolclass=NullPool)
    now = datetime.now(UTC)
    try:
        with engine.begin() as conn:
            row = conn.execute(text("SELECT id FROM storage_profile WHERE public_id = :pid"), {"pid": profile["public_id"]}).first()
            values = {column: profile.get(column) for column in PROFILE_COLUMNS}
            if row is None and profile["provider"] == "filesystem":
                row = conn.execute(text("SELECT id FROM storage_profile WHERE provider = 'filesystem'")).first()
            if row is not None:
                profile_id = int(row.id)
                assignments = ", ".join(f"{column} = :{column}" for column in PROFILE_COLUMNS)
                conn.execute(text(f"UPDATE storage_profile SET {assignments}, is_enabled = true, config_version = config_version + 1, updated_at = NOW() WHERE id = :id"),
                             {**values, "id": profile_id})
            else:
                name = profile["name"]
                if conn.execute(text("SELECT 1 FROM storage_profile WHERE name = :n"), {"n": name}).first():
                    name = f"{name} ({note} {now:%Y-%m-%d %H:%M})"
                columns = ", ".join(PROFILE_COLUMNS)
                params = ", ".join(f":{column}" for column in PROFILE_COLUMNS)
                profile_id = int(conn.execute(text(f"""
                    INSERT INTO storage_profile (public_id, name, {columns}, is_enabled, is_builtin, last_test_ok)
                    VALUES (:public_id, :name, {params}, true, false, true) RETURNING id
                """), {**values, "public_id": profile["public_id"], "name": name}).scalar_one())
            if conn.execute(text("SELECT 1 FROM storage_generation WHERE generation = :g"), {"g": generation}).first():
                raise RestoreError("generation_exists", f"Generation {generation} ist in der wiederhergestellten Datenbank bereits vergeben")
            conn.execute(text("""
                UPDATE storage_generation SET status = 'retained', deactivated_at = :now, retain_until = :until
                WHERE status = 'active'
            """), {"now": now, "until": now + timedelta(days=fallback_days)})
            conn.execute(text("""
                INSERT INTO storage_generation (profile_id, generation, status, activated_at, object_count, total_bytes)
                SELECT :pid, :g, 'active', :now, COUNT(*), COALESCE(SUM(size_bytes), 0) FROM storage_object WHERE status = 'active'
            """), {"pid": profile_id, "g": generation, "now": now})
            conn.execute(text("""
                UPDATE storage_state SET active_profile_id = :pid, active_generation = :g, write_fenced = false, fence_reason = NULL,
                       fenced_at = NULL, backup_hold_id = NULL, backup_hold_generation = NULL, backup_hold_since = NULL, updated_at = NOW()
                WHERE id = 1
            """), {"pid": profile_id, "g": generation})
            conn.execute(text("UPDATE storage_object SET generation = :g WHERE status = 'active'"), {"g": generation})
            cancelled_migrations = conn.execute(text("""
                UPDATE storage_migration SET state = 'cancelled', finished_at = NOW(), updated_at = NOW(), lease_owner = NULL,
                       lease_expires_at = NULL, last_error = 'Durch Wiederherstellung aus dem Backup beendet'
                WHERE state NOT IN ('completed', 'failed', 'cancelled')
            """)).rowcount
            cancelled_windows = conn.execute(text("""
                UPDATE maintenance_window SET state = 'cancelled', ended_at = NOW(), updated_at = NOW()
                WHERE state IN ('scheduled', 'preparing', 'active', 'verifying', 'failed', 'overdue')
                  AND COALESCE(source_job_type, '') LIKE 'storage%'
            """)).rowcount
            interrupted_jobs = conn.execute(text("""
                UPDATE backup_job SET state = 'interrupted', finished_at = NOW(), lease_owner = NULL, lease_expires_at = NULL,
                       error_code = 'restored', error_message = 'Stand vor der Wiederherstellung'
                WHERE state IN ('queued', 'preparing', 'running', 'verifying')
            """)).rowcount
    finally:
        engine.dispose()
    return {"profile_id": profile_id, "generation": generation, "cancelled_migrations": cancelled_migrations,
            "cancelled_storage_windows": cancelled_windows, "interrupted_backup_jobs": interrupted_jobs}


def reference_report(database_url: str, restored_keys: Iterator[tuple[str, str]] | None = None) -> dict[str, Any]:
    """Prüft die wiederhergestellte Datenbank: Verweise (stored_file, Logos, Vorlagen, Snapshots)
    auf registrierte Objekte und - falls übergeben - Register gegen tatsächlich
    wiederhergestellte Keys. Liefert Zähler und die ersten Abweichungen."""
    from sqlalchemy.orm import Session

    from app.services.storage_migration_service import database_references

    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            conn.execute(text("CREATE TEMP TABLE restored_key (namespace text, key text, PRIMARY KEY (namespace, key)) ON COMMIT PRESERVE ROWS"))
            restored_count = 0
            if restored_keys is not None:
                batch: list[dict[str, str]] = []
                for namespace, key in restored_keys:
                    batch.append({"ns": namespace, "key": key})
                    if len(batch) >= 5000:
                        conn.execute(text("INSERT INTO restored_key VALUES (:ns, :key) ON CONFLICT DO NOTHING"), batch)
                        restored_count += len(batch)
                        batch = []
                if batch:
                    conn.execute(text("INSERT INTO restored_key VALUES (:ns, :key) ON CONFLICT DO NOTHING"), batch)
                    restored_count += len(batch)
            registry_count = int(conn.execute(text("SELECT COUNT(*) FROM storage_object WHERE status = 'active'")).scalar_one())
            registry_missing: list[dict[str, str]] = []
            if restored_keys is not None:
                registry_missing = [dict(r._mapping) for r in conn.execute(text("""
                    SELECT o.namespace, o.key FROM storage_object o
                    LEFT JOIN restored_key r ON r.namespace = o.namespace AND r.key = o.key
                    WHERE o.status = 'active' AND r.key IS NULL ORDER BY 1, 2 LIMIT 500
                """))]
                registry_missing_count = int(conn.execute(text("""
                    SELECT COUNT(*) FROM storage_object o LEFT JOIN restored_key r ON r.namespace = o.namespace AND r.key = o.key
                    WHERE o.status = 'active' AND r.key IS NULL
                """)).scalar_one())
            else:
                registry_missing_count = 0
            with Session(bind=conn) as session:
                refs = database_references(session)
            missing_refs: list[dict[str, str]] = []
            exact = [(ns, key) for (ns, key), kind in refs.items() if not kind.startswith("prefix:")]
            for start in range(0, len(exact), 2000):
                chunk = exact[start:start + 2000]
                present = set(conn.execute(text("""
                    SELECT namespace, key FROM storage_object WHERE status = 'active' AND (namespace, key) IN (SELECT * FROM unnest(CAST(:ns AS text[]), CAST(:keys AS text[])))
                """), {"ns": [c[0] for c in chunk], "keys": [c[1] for c in chunk]}).all())
                missing_refs += [{"namespace": ns, "key": key, "kind": refs[(ns, key)]} for ns, key in chunk if (ns, key) not in present]
            for (ns, prefix), kind in refs.items():
                if kind.startswith("prefix:") and conn.execute(text(
                        "SELECT 1 FROM storage_object WHERE namespace = :ns AND status = 'active' AND left(key, length(:p)) = :p LIMIT 1"),
                        {"ns": ns, "p": prefix}).first() is None:
                    missing_refs.append({"namespace": ns, "key": prefix, "kind": kind})
            revision = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            tenants = int(conn.execute(text("SELECT COUNT(*) FROM tenant")).scalar_one())
            users = int(conn.execute(text("SELECT COUNT(*) FROM app_user")).scalar_one())
            conn.rollback()
    finally:
        engine.dispose()
    return {
        "alembic_revision": revision, "tenants": tenants, "users": users, "references": len(refs),
        "missing_references": missing_refs[:200], "missing_reference_count": len(missing_refs),
        "registry_objects": registry_count, "restored_keys": restored_count,
        "registry_without_object": registry_missing, "registry_without_object_count": registry_missing_count,
        "consistent": not missing_refs and registry_missing_count == 0,
    }


def restored_keys_from_manifest(view: RepositoryView, archive: str, metadata: dict[str, Any], work_dir: Path,
                                exclude_shas: set[str] | None = None) -> Iterator[tuple[str, str]]:
    excluded = exclude_shas or set()
    for chunk in iter_manifest_slices(view, archive, metadata, work_dir):
        for entry in chunk:
            if entry.sha256 not in excluded:
                yield entry.namespace, entry.key


__all__ = [
    "RestoreError", "load_restore_point", "schema_compatibility", "run_alembic_upgrade", "restore_database",
    "restore_objects", "verify_stream", "configure_restored_database", "reference_report", "restored_keys_from_manifest",
    "ensure_empty_generation", "purge_generation_objects", "ObjectInfo", "StorageError",
]
