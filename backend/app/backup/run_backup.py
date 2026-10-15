"""Ein Backup-Lauf (Auftragsart "backup") - Ablauf und Konsistenzverfahren siehe
docs-site/docs/technik/backup/architektur.md.

Phasen (job.checkpoint["phase"]), jede wiederaufnehmbar:
  capture    Backup-Hold setzen, Snapshot exportieren, pg_dump + Inventar + Mandanten im selben
             Snapshot, Dump prüfen (Staging-Verzeichnis des Auftrags)
  transfer   neue Inhalte in Pool-Archive streamen (bereits indexierte werden übersprungen)
  finalize   Manifest schreiben, Wiederherstellungspunkt (rp-Archiv) anlegen, Nachprüfung
Ein Neustart nach "capture" setzt mit derselben Snapshot-Erfassung fort, solange das
Staging-Verzeichnis existiert und der Hold noch dieser Sicherung gehört; sonst neue Erfassung.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import shutil
import subprocess
import threading
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.backup import jobs
from app.backup.borg import Borg, BorgError
from app.backup.config import BackupConfig
from app.backup.index import ContentIndex
from app.backup.manifest import (
    DUMP_PATH,
    GLOBALS_PATH,
    MANIFEST_PATH,
    METADATA_PATH,
    POOL_NAME,
    README_PATH,
    RECOVERY_README,
    ManifestEntry,
    ManifestWriter,
    build_metadata,
    pool_archive_name,
    pool_path,
    rp_archive_name,
)
from app.backup.pgtools import PgTarget, PgToolError, PgTools
from app.backup.repository import RepositoryView
from app.backup.tarstream import ContentMismatch, StreamBroken, TarStreamWriter
from app.core.objstore_client import (
    BACKUP_HOLD_PREFIX,
    NAMESPACES,
    Backend,
    ObjectNotFound,
    StorageError,
    backup_hold_key,
    validate_key,
)
from app.models import BackupJob, BackupSet, StorageGeneration, StorageMigration, StorageProfile, StorageState

_logger = logging.getLogger("hocx.backup.run")

HOLD_LOCK_TIMEOUT = "15s"
# Ein Hold, der länger besteht, wird nicht weiterverwendet (zu viele Copy-on-Write-Kopien):
# Neustart der Erfassung mit frischem Snapshot.
MAX_HOLD_AGE = timedelta(hours=24)
PROGRESS_INTERVAL_SECONDS = 5
_INVENTORY_CHUNK = 1000


@dataclass
class RunEnv:
    config: BackupConfig
    borg: Borg
    engine: Any
    database_url: str
    store: Any  # ObjectStore
    profile_config: Any  # (profile, generation) -> ProfileConfig
    app_version: str


def _staging(env: RunEnv, job_id: uuid.UUID) -> Path:
    path = env.config.staging_dir / f"job-{job_id.hex}"
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _free_bytes(path: Path) -> int:
    usage = shutil.disk_usage(path)
    return usage.free


# --- Backup-Hold ------------------------------------------------------------------------------


def hold_backend(env: RunEnv, db: Session, profile_id: int, generation: int) -> Backend:
    profile = db.get(StorageProfile, profile_id)
    if profile is None:
        raise jobs.JobFailure("profile_missing", "Speicherprofil der gesicherten Generation fehlt")
    return env.store.make_backend(env.profile_config(profile, generation))


def acquire_hold(db: Session, hold_id: uuid.UUID) -> tuple[int, int] | None:
    """Setzt den Hold auf die aktive Generation. Das UPDATE wartet (begrenzt) auf alle offenen
    Schreibtransaktionen - danach sichert jeder Schreiber per Copy-on-Write."""
    db.commit()
    db.execute(text(f"SET LOCAL lock_timeout = '{HOLD_LOCK_TIMEOUT}'"))
    try:
        row = _update_hold(db, hold_id)
    except OperationalError:
        # Lange Schreibtransaktion hält storage_state - nicht warten, später erneut.
        db.rollback()
        return None
    db.commit()
    return (int(row.active_profile_id), int(row.active_generation)) if row else None


def _update_hold(db: Session, hold_id: uuid.UUID) -> Any:
    return db.execute(text("""
        UPDATE storage_state SET backup_hold_id = :hold, backup_hold_generation = active_generation,
               backup_hold_since = COALESCE(CASE WHEN backup_hold_id = :hold THEN backup_hold_since END, NOW()),
               updated_at = NOW()
        WHERE id = 1 AND NOT write_fenced AND (backup_hold_id IS NULL OR backup_hold_id = :hold)
        RETURNING active_profile_id, active_generation
    """), {"hold": hold_id}).first()


def release_hold(db: Session, hold_id: uuid.UUID) -> bool:
    result = db.execute(text("""
        UPDATE storage_state SET backup_hold_id = NULL, backup_hold_generation = NULL, backup_hold_since = NULL, updated_at = NOW()
        WHERE id = 1 AND backup_hold_id = :hold
    """), {"hold": hold_id})
    db.commit()
    return bool(result.rowcount)


def purge_hold_area(backend: Backend, hold_id: uuid.UUID) -> int:
    """Löscht die Copy-on-Write-Kopien eines beendeten Holds (nur dieses Präfix)."""
    prefix = f"{BACKUP_HOLD_PREFIX}{hold_id.hex}/"
    removed = 0
    for namespace in NAMESPACES:
        for info in list(backend.list(namespace, prefix)):
            if info.key.startswith(prefix):
                backend.delete(namespace, info.key)
                removed += 1
    return removed


def clear_stale_hold(env: RunEnv, db: Session, *, own_hold: uuid.UUID | None) -> None:
    """Ein Hold ohne laufenden Besitzer (Absturz, abgebrochener Auftrag) wird gelöst und sein
    Kopienbereich gelöscht. Besitzer ist immer der Backup-Auftrag mit checkpoint.hold_id."""
    state = db.get(StorageState, 1, populate_existing=True)
    if state is None or state.backup_hold_id is None or state.backup_hold_id == own_hold:
        return
    owner = db.scalars(select(BackupJob).where(BackupJob.checkpoint["hold_id"].astext == str(state.backup_hold_id))).first()
    if owner is not None and owner.state in jobs.OPEN_JOB_STATES:
        raise jobs.JobWait(60, "hold_owned_by_other_job")
    generation = int(state.backup_hold_generation)
    gen_row = db.scalars(select(StorageGeneration).where(StorageGeneration.generation == generation)).first()
    hold_id = state.backup_hold_id
    release_hold(db, hold_id)
    if gen_row is not None and gen_row.status not in ("purged", "purging"):
        try:
            purge_hold_area(hold_backend(env, db, gen_row.profile_id, generation), hold_id)
        except StorageError:
            _logger.warning("Kopien des verwaisten Backup-Holds %s konnten nicht gelöscht werden", hold_id, exc_info=True)


# --- Erfassung --------------------------------------------------------------------------------


def _registry_trusted(env: RunEnv, db: Session, profile: StorageProfile) -> bool:
    if profile.provider != "filesystem":
        return True
    if env.config.trust_filesystem_registry:
        return True
    return db.scalar(select(StorageMigration.id).where(StorageMigration.kind == "initial", StorageMigration.state == "completed").limit(1)) is not None


def _dangling_references(session: Session, conn: Any) -> dict[str, Any]:
    """DB-Verweise im Snapshot, deren Objekt im Register fehlt (vorbestehende Inkonsistenz -
    nicht sicherbar, wird als Warnung im Backup vermerkt)."""
    from app.services.storage_migration_service import database_references

    refs = database_references(session)
    missing: list[dict[str, str]] = []
    exact = [(ns, key) for (ns, key), kind in refs.items() if not kind.startswith("prefix:")]
    for start in range(0, len(exact), _INVENTORY_CHUNK):
        chunk = exact[start:start + _INVENTORY_CHUNK]
        present = set(conn.execute(text("""
            SELECT o.namespace, o.key FROM storage_object o
            JOIN jsonb_to_recordset(CAST(:rows AS jsonb)) AS x(ns text, key text) ON o.namespace = x.ns AND o.key = x.key
            WHERE o.status = 'active'
        """), {"rows": json.dumps([{"ns": ns, "key": key} for ns, key in chunk])}).all())
        missing += [{"namespace": ns, "key": key, "kind": refs[(ns, key)]} for ns, key in chunk if (ns, key) not in present]
    for (ns, prefix), kind in refs.items():
        if kind.startswith("prefix:"):
            found = conn.execute(text("SELECT 1 FROM storage_object WHERE namespace = :ns AND status = 'active' AND left(key, length(:p)) = :p LIMIT 1"),
                                 {"ns": ns, "p": prefix}).first()
            if found is None:
                missing.append({"namespace": ns, "key": prefix, "kind": kind})
    return {"count": len(missing), "items": missing[:200], "references": len(refs)}


def capture(env: RunEnv, db: Session, ctx: jobs.JobCtx, job: BackupJob, backup_id: uuid.UUID) -> dict[str, Any]:
    staging = _staging(env, ctx.job_id)
    state = db.get(StorageState, 1, populate_existing=True)
    if state.write_fenced:
        raise jobs.JobWait(120, "storage_fenced")
    cutting_over = db.scalar(select(StorageMigration.id).where(StorageMigration.state == "cutting_over").limit(1))
    if cutting_over is not None:
        raise jobs.JobWait(120, "storage_cutover")
    profile = db.get(StorageProfile, state.active_profile_id)
    if not _registry_trusted(env, db, profile):
        raise jobs.JobFailure(
            "storage_registry_incomplete",
            "Der Dateispeicher läuft noch auf dem bisherigen Dateisystem ohne vollständiges Objektregister - "
            "zuerst die Erstmigration abschliessen (oder BACKUP_TRUST_FILESYSTEM_REGISTRY bewusst setzen).",
        )
    clear_stale_hold(env, db, own_hold=backup_id)

    # Staging-Budget: der Dump ist im Custom-Format praktisch immer kleiner als die Datenbank.
    db_size = int(db.scalar(text("SELECT pg_database_size(current_database())")) or 0)
    needed = db_size + 256 * 1024 * 1024
    budget = min(env.config.staging_max_bytes, _free_bytes(staging))
    if needed > budget:
        raise jobs.JobFailure("staging_insufficient",
                              f"Zu wenig lokaler Platz für den Datenbank-Dump: benötigt ca. {needed // 1024 ** 2} MiB, verfügbar {budget // 1024 ** 2} MiB")

    held = acquire_hold(db, backup_id)
    if held is None:
        raise jobs.JobWait(30, "hold_unavailable")
    profile_id, generation = held
    jobs.checkpoint(db, ctx, hold_id=str(backup_id), phase="capture")
    jobs.event(db, ctx, "hold_acquired", f"Backup-Hold auf Generation {generation} gesetzt")
    db.commit()

    dump_path = staging / "hocx.pgdump"
    inventory_path = staging / "inventory.jsonl.gz"
    dump_path.unlink(missing_ok=True)
    target = PgTarget.from_url(env.database_url)
    pg_tools = PgTools(target)
    try:
        return _capture_snapshot(env, db, ctx, backup_id, staging, dump_path, inventory_path, pg_tools, profile_id, generation)
    finally:
        pg_tools.close()


def _capture_snapshot(env: RunEnv, db: Session, ctx: jobs.JobCtx, backup_id: uuid.UUID, staging: Path, dump_path: Path,
                      inventory_path: Path, pg_tools: PgTools, profile_id: int, generation: int) -> dict[str, Any]:
    with env.engine.connect() as raw:
        conn = raw.execution_options(isolation_level="REPEATABLE READ")
        transaction = conn.begin()
        try:
            conn.execute(text("SET TRANSACTION READ ONLY"))
            snapshot_id = conn.execute(text("SELECT pg_export_snapshot()")).scalar_one()
            check = conn.execute(text("""
                SELECT s.backup_hold_id, s.backup_hold_generation, s.active_generation, s.active_profile_id, p.name, p.provider
                FROM storage_state s JOIN storage_profile p ON p.id = s.active_profile_id WHERE s.id = 1
            """)).one()
            if check.backup_hold_id != backup_id or check.backup_hold_generation != generation or check.active_generation != generation:
                raise jobs.JobWait(10, "generation_changed_during_capture")
            snapshot_at = conn.execute(text("SELECT NOW()")).scalar_one()
            server_version = conn.execute(text("SHOW server_version")).scalar_one()
            server_major = int(conn.execute(text("SHOW server_version_num")).scalar_one()) // 10000
            if PgTools.client_major("pg_dump") < server_major:
                raise jobs.JobFailure("pg_client_too_old", f"pg_dump ist älter als PostgreSQL {server_major}")
            alembic_revision = conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).scalar()
            outbox_seq = int(conn.execute(text("SELECT COALESCE(MAX(seq), 0) FROM storage_change_outbox")).scalar_one())
            dump_thread_error: list[BaseException] = []

            def run_dump() -> None:
                try:
                    pg_tools.dump(dump_path, snapshot=snapshot_id)
                except BaseException as exc:  # noqa: BLE001 - wird im Hauptthread ausgewertet
                    dump_thread_error.append(exc)

            dump_thread = threading.Thread(target=run_dump, daemon=True)
            dump_thread.start()
            count = total = unhashed = 0
            with gzip.open(inventory_path, "wt", encoding="utf-8") as inventory:
                result = conn.execution_options(stream_results=True, yield_per=5000).execute(text("""
                    SELECT namespace, key, size_bytes, sha256, version FROM storage_object WHERE status = 'active'
                    ORDER BY namespace, key
                """))
                for row in result:
                    validate_key(row.key)
                    inventory.write(json.dumps({"ns": row.namespace, "key": row.key, "size": row.size_bytes, "sha256": row.sha256,
                                                "version": int(row.version)}, separators=(",", ":")) + "\n")
                    count += 1
                    total += int(row.size_bytes or 0)
                    unhashed += 0 if row.sha256 else 1
                    if count % 20000 == 0:
                        ctx.check()
            tenants = [dict(row._mapping) for row in conn.execute(text(r"""
                WITH usage AS (
                  SELECT CAST(substring(key from '(?:^|/)tenant-([0-9]+)/') AS bigint) AS tenant_id,
                         COUNT(*) AS objects, COALESCE(SUM(size_bytes), 0) AS bytes
                  FROM storage_object WHERE status = 'active' AND key ~ '(^|/)tenant-[0-9]+/' GROUP BY 1)
                SELECT t.id, CAST(t.public_id AS text) AS public_id, t.name,
                       (SELECT COUNT(*) FROM app_user u WHERE u.tenant_id = t.id) AS users,
                       COALESCE(usage.objects, 0) AS objects, COALESCE(usage.bytes, 0) AS bytes
                FROM tenant t LEFT JOIN usage ON usage.tenant_id = t.id ORDER BY t.name
            """))]
            with Session(bind=conn) as session:
                dangling = _dangling_references(session, conn)
            dump_thread.join()
            if dump_thread_error:
                exc = dump_thread_error[0]
                raise jobs.JobFailure(getattr(exc, "code", "pg_dump_failed"), f"pg_dump fehlgeschlagen: {exc}")
        finally:
            transaction.rollback()
    globals_path = staging / "globals.sql"
    has_globals = pg_tools.dump_globals(globals_path)
    try:
        toc = pg_tools.list_dump(dump_path)
    except PgToolError as exc:
        raise jobs.JobFailure("pg_dump_invalid", f"Dump nicht lesbar: {exc}") from exc
    if not any("TABLE DATA public alembic_version" in line for line in toc):
        raise jobs.JobFailure("pg_dump_invalid", "Dump enthält keine Daten der Tabelle alembic_version")
    for tenant in tenants:
        tenant["id"] = int(tenant["id"])
        tenant["users"] = int(tenant["users"])
        tenant["objects"] = int(tenant["objects"])
        tenant["bytes"] = int(tenant["bytes"])
    captured = {
        "phase": "transfer",
        "hold_id": str(backup_id),
        "snapshot_at": snapshot_at.astimezone(UTC).isoformat(),
        "profile_id": profile_id,
        "generation": generation,
        "profile_name": check.name,
        "profile_provider": check.provider,
        "alembic_revision": alembic_revision,
        "pg_server_version": server_version,
        "outbox_seq": outbox_seq,
        "object_count": count,
        "object_bytes": total,
        "unhashed_objects": unhashed,
        "dump_sha256": _sha256_file(dump_path),
        "dump_bytes": dump_path.stat().st_size,
        "dump_toc_entries": len(toc),
        "has_globals": has_globals,
        "tenants": tenants,
        "dangling_references": dangling,
        "staging": str(staging),
    }
    jobs.checkpoint(db, ctx, **captured)
    jobs.event(db, ctx, "captured", f"Snapshot erfasst: {count} Objekte, Dump {captured['dump_bytes']} Bytes",
               generation=generation, objects=count, dangling=dangling["count"])
    db.commit()
    return captured


# --- Übertragung ------------------------------------------------------------------------------


@dataclass
class InventoryEntry:
    namespace: str
    key: str
    size: int | None
    sha256: str | None
    version: int


def iter_inventory(path: Path) -> Iterator[list[InventoryEntry]]:
    chunk: list[InventoryEntry] = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            data = json.loads(line)
            chunk.append(InventoryEntry(data["ns"], data["key"], data["size"], data["sha256"], data["version"]))
            if len(chunk) >= _INVENTORY_CHUNK:
                yield chunk
                chunk = []
    if chunk:
        yield chunk


class _Transfer:
    def __init__(self, env: RunEnv, db: Session, ctx: jobs.JobCtx, backup_id: uuid.UUID, captured: dict[str, Any]) -> None:
        self.env = env
        self.db = db
        self.ctx = ctx
        self.backup_id = backup_id
        self.captured = captured
        self.index = ContentIndex(db)
        self.backend = hold_backend(env, db, captured["profile_id"], captured["generation"])
        self.hold_id = uuid.UUID(captured["hold_id"])
        self.missing: dict[tuple[str, str], str] = {}
        self.use_hold: set[str] = set()
        self.resolved_sha: dict[tuple[str, str], str] = {}
        self.new_objects = 0
        self.new_bytes = 0
        self.processed = 0
        self.dedup_bytes = 0
        self.pools_created: list[str] = []
        self._last_progress = 0.0

    # Quelle eines Inhalts: Original oder Copy-on-Write-Kopie im Hold.
    def _open(self, entry: InventoryEntry, sha: str) -> Iterator[bytes]:
        if sha not in self.use_hold:
            try:
                return self.backend.open_read(entry.namespace, entry.key)
            except ObjectNotFound:
                self.use_hold.add(sha)
        return self.backend.open_read(entry.namespace, backup_hold_key(self.hold_id, sha))

    def _hash_unregistered(self, entry: InventoryEntry) -> str | None:
        """Register ohne SHA-256 (Altbestand): Inhalt einmal lesen und hashen."""
        digest = hashlib.sha256()
        size = 0
        try:
            for chunk in self.backend.open_read(entry.namespace, entry.key):
                digest.update(chunk)
                size += len(chunk)
        except ObjectNotFound:
            return None
        entry.size = size
        return digest.hexdigest()

    def _progress(self, *, force: bool = False, **extra: Any) -> None:
        now = time.monotonic()
        if not force and now - self._last_progress < PROGRESS_INTERVAL_SECONDS:
            return
        self._last_progress = now
        jobs.progress(self.db, self.ctx, phase="transfer", objects_total=self.captured["object_count"],
                      bytes_total=self.captured["object_bytes"], objects_done=self.processed, new_objects=self.new_objects,
                      new_bytes=self.new_bytes, missing=len(self.missing), **extra)

    def _next_pool_index(self) -> int:
        prefix = f"hocx-pool-{self.backup_id.hex}-"
        existing = [int(name.rsplit("-", 1)[1]) for name in RepositoryView(self.env.borg).pool_archives() if name.startswith(prefix)]
        return max(existing, default=-1) + 1

    def _write_batch(self, name: str, batch: list[tuple[InventoryEntry, str]]) -> dict[str, int]:
        """Schreibt einen Batch als Pool-Archiv. Bei einem Inhalt, der nicht zum erwarteten
        SHA-256 passt, wird borg abgebrochen (kein Archiv) und der Batch mit der Hold-Kopie bzw.
        ohne das Objekt wiederholt."""
        while True:
            process = self.env.borg.import_tar(name, comment=f"hocX Objektinhalte, Backup {self.backup_id}")
            writer = TarStreamWriter(process.stdin)
            written: dict[str, int] = {}
            restart = False
            try:
                for entry, sha in batch:
                    self.ctx.check()
                    if (entry.namespace, entry.key) in self.missing or sha in written:
                        continue
                    try:
                        chunks = self._open(entry, sha)
                    except ObjectNotFound:
                        self.missing[(entry.namespace, entry.key)] = "not_found"
                        continue
                    try:
                        writer.add_chunks(pool_path(sha), int(entry.size or 0), chunks, expected_sha256=sha)
                    except ContentMismatch as exc:
                        if sha in self.use_hold:
                            self.missing[(entry.namespace, entry.key)] = f"content_{exc.reason}"
                        else:
                            self.use_hold.add(sha)
                        restart = True
                        break
                    except ObjectNotFound:
                        # Erst beim Lesen verschwunden: der Header ist schon geschrieben.
                        if sha in self.use_hold:
                            self.missing[(entry.namespace, entry.key)] = "not_found"
                        else:
                            self.use_hold.add(sha)
                        restart = True
                        break
                    written[sha] = int(entry.size or 0)
                    self._progress(current_pool=name)
                if restart:
                    process.abort()
                    jobs.event(self.db, self.ctx, "batch_restart", f"Pool {name}: Inhalt geändert, Batch wird mit Hold-Kopie wiederholt", level="warning")
                    self.db.commit()
                    continue
                writer.close()
            except StreamBroken as exc:
                error = process.failure()
                raise error from exc
            except BaseException:
                process.abort()
                raise
            if not written:
                process.abort()
                return {}
            stats = process.finish()
            archive_id = stats.get("archive", {}).get("id")
            self.index.add_pool(name, archive_id, written, backup_set_id=None)
            self.db.commit()
            self.pools_created.append(name)
            jobs.event(self.db, self.ctx, "pool_written", f"{name}: {len(written)} Inhalte", objects=len(written), bytes=sum(written.values()))
            self.db.commit()
            return written

    def run(self) -> None:
        staging = Path(self.captured["staging"])
        pool_index = self._next_pool_index()
        batch: list[tuple[InventoryEntry, str]] = []
        batch_bytes = 0
        batch_shas: set[str] = set()

        def flush() -> None:
            nonlocal pool_index, batch, batch_bytes, batch_shas
            if not batch:
                return
            written = self._write_batch(pool_archive_name(self.backup_id, pool_index), batch)
            if written:
                pool_index += 1
                self.new_objects += len(written)
                self.new_bytes += sum(written.values())
            jobs.checkpoint(self.db, self.ctx, pool_next=pool_index)
            batch, batch_bytes, batch_shas = [], 0, set()

        for chunk in iter_inventory(staging / "inventory.jsonl.gz"):
            self.ctx.check()
            for entry in chunk:
                if not entry.sha256:
                    sha = self._hash_unregistered(entry)
                    if sha is None:
                        self.missing[(entry.namespace, entry.key)] = "not_found"
                        continue
                    entry.sha256 = sha
                    self.resolved_sha[(entry.namespace, entry.key)] = sha
            known = self.index.lookup(e.sha256 for e in chunk if e.sha256)
            for entry in chunk:
                self.processed += 1
                sha = entry.sha256
                if sha is None or (entry.namespace, entry.key) in self.missing:
                    continue
                if sha in known:
                    self.dedup_bytes += int(entry.size or 0)
                    continue
                if sha in batch_shas:
                    continue
                batch.append((entry, sha))
                batch_shas.add(sha)
                batch_bytes += int(entry.size or 0)
                if batch_bytes >= self.env.config.batch_max_bytes or len(batch) >= self.env.config.batch_max_objects:
                    flush()
            self._progress()
        flush()
        self._progress(force=True)


# --- Abschluss --------------------------------------------------------------------------------


def _write_manifest(transfer: _Transfer, backup_id: uuid.UUID, staging: Path) -> tuple[Path, str, int, int, list[dict[str, str]]]:
    path = staging / "manifest.jsonl.gz"
    writer = ManifestWriter(path, backup_id=backup_id, generation=transfer.captured["generation"])
    missing: list[dict[str, str]] = []
    for chunk in iter_inventory(staging / "inventory.jsonl.gz"):
        for entry in chunk:
            entry.sha256 = entry.sha256 or transfer.resolved_sha.get((entry.namespace, entry.key))
        pools = transfer.index.lookup(e.sha256 for e in chunk if e.sha256)
        for entry in chunk:
            reason = transfer.missing.get((entry.namespace, entry.key))
            pool = pools.get(entry.sha256 or "")
            if reason is None and pool is None:
                reason = "not_in_repository"
            if reason is not None:
                missing.append({"namespace": entry.namespace, "key": entry.key, "reason": reason})
                continue
            writer.add(ManifestEntry(entry.namespace, entry.key, int(entry.size or 0), entry.sha256, entry.version, pool))  # type: ignore[arg-type]
    sha = writer.close()
    return path, sha, writer.count, writer.total_bytes, missing


def _verify_new_pools(env: RunEnv, transfer: _Transfer) -> None:
    """Die in diesem Lauf geschriebenen Pool-Archive enthalten genau die indexierten Inhalte."""
    view = RepositoryView(env.borg)
    from app.models import BackupContent

    for pool in transfer.pools_created:
        actual = view.pool_contents(pool)
        expected = dict(transfer.db.execute(select(BackupContent.sha256, BackupContent.size_bytes).where(BackupContent.pool_archive == pool)).all())
        if any(actual.get(sha) != size for sha, size in expected.items()):
            raise jobs.JobFailure("pool_verification_failed", f"Pool-Archiv {pool} enthält nicht alle erwarteten Inhalte")


def finalize(env: RunEnv, db: Session, ctx: jobs.JobCtx, job: BackupJob, backup_id: uuid.UUID, captured: dict[str, Any],
             transfer: _Transfer) -> BackupSet:
    staging = Path(captured["staging"])
    _verify_new_pools(env, transfer)
    manifest_path, manifest_sha, count, total, missing = _write_manifest(transfer, backup_id, staging)
    snapshot_at = datetime.fromisoformat(captured["snapshot_at"])
    archive = rp_archive_name(snapshot_at, backup_id)
    dangling = captured.get("dangling_references") or {"count": 0, "items": []}
    warnings: list[dict[str, Any]] = []
    if dangling.get("count"):
        warnings.append({"code": "dangling_references", "count": dangling["count"], "items": dangling.get("items", [])[:50]})
    if missing:
        warnings.append({"code": "missing_objects", "count": len(missing), "items": missing[:200]})
    metadata = build_metadata(
        backup_id=str(backup_id),
        archive=archive,
        snapshot_at=captured["snapshot_at"],
        created_at=datetime.now(UTC).isoformat(),
        trigger=job.trigger,
        app_version=env.app_version,
        alembic_revision=captured.get("alembic_revision"),
        pg_server_version=captured.get("pg_server_version"),
        pg_dump_version=PgTools.client_major("pg_dump"),
        storage={"profile_name": captured["profile_name"], "provider": captured["profile_provider"], "generation": captured["generation"],
                 "outbox_seq": captured["outbox_seq"]},
        object_count=count,
        object_bytes=total,
        inventory_count=captured["object_count"],
        missing_objects=len(missing),
        manifest_sha256=manifest_sha,
        db_dump_sha256=captured["dump_sha256"],
        db_dump_bytes=captured["dump_bytes"],
        consistency={"method": "backup_hold_copy_on_write", "snapshot": "pg_export_snapshot", "hold_id": captured["hold_id"]},
        tenants=captured.get("tenants", []),
        warnings=warnings,
        verification={"state": "unverified"},
    )
    metadata_bytes = json.dumps(metadata, ensure_ascii=False, indent=1).encode("utf-8")
    process = env.borg.import_tar(archive, comment=f"hocX Wiederherstellungspunkt {backup_id}")
    writer = TarStreamWriter(process.stdin)
    try:
        writer.add_bytes(METADATA_PATH, metadata_bytes)
        writer.add_file(MANIFEST_PATH, manifest_path)
        writer.add_file(DUMP_PATH, staging / "hocx.pgdump")
        if captured.get("has_globals") and (staging / "globals.sql").exists():
            writer.add_file(GLOBALS_PATH, staging / "globals.sql")
        writer.add_bytes(README_PATH, RECOVERY_README.encode("utf-8"))
        writer.close()
    except StreamBroken as exc:
        raise process.failure() from exc
    except BaseException:
        process.abort()
        raise
    stats = process.finish()
    archive_stats = stats.get("archive", {})
    jobs.event(db, ctx, "restore_point_written", f"Wiederherstellungspunkt {archive} geschrieben")
    db.commit()

    # Nachprüfung: Archiv lesbar, alle Pflichtdateien mit erwarteter Grösse, Metadaten unverändert.
    items = {item["path"]: item["size"] for item in env.borg.iter_items(archive)}
    expected = {METADATA_PATH: len(metadata_bytes), MANIFEST_PATH: manifest_path.stat().st_size, DUMP_PATH: captured["dump_bytes"]}
    problems = [path for path, size in expected.items() if items.get(path) != size]
    if not problems:
        with env.borg.extract_stream(archive, METADATA_PATH) as stream:
            if hashlib.sha256(stream.read()).hexdigest() != hashlib.sha256(metadata_bytes).hexdigest():
                problems.append(METADATA_PATH)
    if problems:
        env.borg.rename(archive, archive + ".invalid")
        raise jobs.JobFailure("restore_point_invalid", f"Wiederherstellungspunkt unvollständig: {', '.join(problems)}")

    state = "partial" if missing else "completed"
    backup_set = db.get(BackupSet, backup_id)
    if backup_set is None:
        backup_set = BackupSet(id=backup_id, archive_name=archive, snapshot_at=snapshot_at)
        db.add(backup_set)
    started = job.started_at or datetime.now(UTC)
    backup_set.archive_id = archive_stats.get("id")
    backup_set.job_id = job.id
    backup_set.state = state
    backup_set.trigger = job.trigger
    backup_set.protected = bool((job.options or {}).get("protected"))
    backup_set.protected_reason = (job.options or {}).get("protected_reason")
    backup_set.finished_at = datetime.now(UTC)
    backup_set.app_version = env.app_version
    backup_set.alembic_revision = captured.get("alembic_revision")
    backup_set.pg_server_version = captured.get("pg_server_version")
    backup_set.profile_name = captured["profile_name"]
    backup_set.profile_provider = captured["profile_provider"]
    backup_set.generation = captured["generation"]
    backup_set.outbox_seq = captured["outbox_seq"]
    backup_set.db_dump_bytes = captured["dump_bytes"]
    backup_set.db_dump_sha256 = captured["dump_sha256"]
    backup_set.manifest_sha256 = manifest_sha
    backup_set.object_count = count
    backup_set.object_bytes = total
    backup_set.new_object_count = transfer.new_objects
    backup_set.new_object_bytes = transfer.new_bytes
    backup_set.deduplicated_bytes = int((archive_stats.get("stats") or {}).get("deduplicated_size") or 0)
    backup_set.duration_seconds = int((datetime.now(UTC) - started).total_seconds())
    backup_set.pool_archives = transfer.pools_created
    backup_set.tenants = captured.get("tenants", [])
    backup_set.warnings = warnings
    db.flush()
    return backup_set


# --- Einstieg ---------------------------------------------------------------------------------


def run(env: RunEnv, db: Session, ctx: jobs.JobCtx) -> str:
    """Treibt den Auftrag bis zum Ende. Liefert den Endzustand (completed/partial)."""
    job = jobs.load(db, ctx)
    backup_id = uuid.UUID((job.checkpoint or {}).get("backup_id") or str(uuid.uuid4()))
    if not (job.checkpoint or {}).get("backup_id"):
        jobs.checkpoint(db, ctx, backup_id=str(backup_id))
    jobs.set_state(db, ctx, "running" if (job.checkpoint or {}).get("phase") else "preparing")
    job = jobs.load(db, ctx)
    preflight_repository(env, db)
    view = RepositoryView(env.borg)
    reconcile = ContentIndex(db).reconcile(view)
    if reconcile["removed"] or reconcile["relisted"] or reconcile["adopted"]:
        jobs.event(db, ctx, "index_reconciled", "Inhaltsindex mit dem Repository abgeglichen", **{k: v for k, v in reconcile.items() if k != "checkpoints"})
        db.commit()

    captured = dict(job.checkpoint or {})
    resumable = (
        captured.get("phase") in ("transfer", "finalize")
        and Path(captured.get("staging", "/nonexistent"), "inventory.jsonl.gz").exists()
        and Path(captured.get("staging", "/nonexistent"), "hocx.pgdump").exists()
    )
    if resumable:
        state = db.get(StorageState, 1, populate_existing=True)
        since = state.backup_hold_since
        if state.backup_hold_id != backup_id or (since is not None and datetime.now(UTC) - since > MAX_HOLD_AGE):
            resumable = False
    if not resumable:
        jobs.set_state(db, ctx, "running", message="Erfassung des Sicherungspunkts")
        captured = capture(env, db, ctx, job, backup_id)
    else:
        jobs.event(db, ctx, "resumed", "Fortsetzung mit bestehender Snapshot-Erfassung")
        db.commit()

    transfer = _Transfer(env, db, ctx, backup_id, captured)
    transfer.run()
    jobs.checkpoint(db, ctx, phase="finalize")
    jobs.set_state(db, ctx, "verifying", message="Wiederherstellungspunkt wird geschrieben und geprüft")
    backup_set = finalize(env, db, ctx, job, backup_id, captured, transfer)
    job = jobs.load(db, ctx)
    final = backup_set.state
    jobs.guarded(db, ctx, backup_set_id=backup_id, warning_count=len(backup_set.warnings or []),
                 result={"archive": backup_set.archive_name, "objects": backup_set.object_count, "new_objects": backup_set.new_object_count,
                         "new_bytes": backup_set.new_object_bytes, "missing": next((w["count"] for w in backup_set.warnings if w["code"] == "missing_objects"), 0)})
    db.commit()
    finish_cleanup(env, db, captured)
    jobs.set_state(db, ctx, final, message=f"Sicherung {backup_set.archive_name} {'vollständig' if final == 'completed' else 'mit fehlenden Objekten'}",
                   level="info" if final == "completed" else "warning")
    return final


def finish_cleanup(env: RunEnv, db: Session, captured: dict[str, Any]) -> None:
    hold_value = captured.get("hold_id")
    if hold_value:
        hold_id = uuid.UUID(hold_value)
        release_hold(db, hold_id)
        if captured.get("profile_id") is not None:
            try:
                purge_hold_area(hold_backend(env, db, captured["profile_id"], captured["generation"]), hold_id)
            except StorageError:
                _logger.warning("Hold-Kopien %s konnten nicht gelöscht werden (nächster Lauf räumt auf)", hold_id, exc_info=True)
    staging = captured.get("staging")
    if staging and Path(staging).is_dir() and Path(staging).parent == env.config.staging_dir:
        shutil.rmtree(staging, ignore_errors=True)


def preflight_repository(env: RunEnv, db: Session) -> dict[str, Any]:
    """Erreichbarkeit, Identität (gepinnte Repository-ID) und Version des Repositories; schreibt
    den Status für Anzeige und Monitoring."""
    from app.backup.status import record_repository_status

    try:
        info = env.borg.repo_info()
    except BorgError as exc:
        record_repository_status(db, env, ok=False, error_code=exc.code, error=str(exc))
        raise
    repo_id = info.get("repository", {}).get("id")
    if env.config.expected_repository_id and repo_id != env.config.expected_repository_id:
        record_repository_status(db, env, ok=False, error_code="repository_id_mismatch", error="Repository-ID weicht vom gepinnten Wert ab")
        raise jobs.JobFailure("repository_id_mismatch", "Das Borg-Repository hat nicht die erwartete Identität (BACKUP_REPOSITORY_ID)")
    encryption = (info.get("encryption") or {}).get("mode")
    if encryption not in ("repokey-blake2", "repokey", "keyfile-blake2", "keyfile"):
        record_repository_status(db, env, ok=False, error_code="repository_not_encrypted", error=f"Verschlüsselung {encryption!r}")
        raise jobs.JobFailure("repository_not_encrypted", "Das Repository ist nicht clientseitig verschlüsselt")
    record_repository_status(db, env, ok=True, info=info)
    return info


__all__ = ["RunEnv", "run", "release_hold", "purge_hold_area", "clear_stale_hold", "preflight_repository", "POOL_NAME"]
