"""Storage-Migrations-Worker (eigener Container "storage-worker", gleiches Image wie das Backend).

    python -m app.workers.storage_worker

Ablauf je Migration (Zustände siehe storage_migration_service.MIGRATION_TRANSITIONS):

  pending -> preflight -> awaiting_confirmation --(Admin: Start)--> inventory -> copying
  -> catching_up -> verifying -> ready_for_cutover --(auto bzw. Admin)--> cutting_over
  -> observing -> completed

Robustheit:
- Lease mit Fencing-Token: genau ein Worker hält eine Migration. Jede Änderung an der Migration
  prüft das Token (UPDATE ... WHERE fencing_token = :token); wer seine Lease verliert, bricht ab
  (LeaseLost) und schreibt nichts mehr. Ein Heartbeat-Thread verlängert die Lease auch während
  grosser Einzelkopien.
- Alles ist idempotent und wiederaufnehmbar: Objektstatus und Journal-Position stehen in der
  Datenbank, bereits korrekt kopierte Objekte (gleiche Grösse + SHA-256 im Ziel) werden
  übersprungen.
- Fehler je Objekt: exponentielles Backoff mit Jitter, Rate-Limits bremsen den ganzen Worker,
  nach max_object_attempts gilt ein Objekt als dauerhaft fehlgeschlagen ("dead") und blockiert
  den Cutover, bis ein Admin es erneut versucht (oder ein bereits in der Quelle fehlendes Objekt
  bewusst bestätigt).
- Der Cutover schaltet nur nach Fence, vollständigem Nachziehen des Journals und finaler
  Integritätsprüfung um - in einer Transaktion zusammen mit der Generation. Scheitert vorher
  etwas, bleibt die Quelle aktiv.
"""

from __future__ import annotations

import io
import logging
import os
import random
import signal
import socket
import tempfile
import threading
import time
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import SessionLocal, engine
from app.core.error_log import record_system_error
from app.core.objstore_client import (
    Backend,
    InvalidObjectKey,
    ObjectNotFound,
    RateLimiter,
    StorageError,
    StorageIntegrityError,
    StorageThrottled,
    StorageUnavailable,
    is_internal_key,
    validate_key,
)
from app.core.storage import get_object_store
from app.models import (
    MaintenanceWindow,
    StorageGeneration,
    StorageMigration,
    StorageMigrationObject,
    StorageObject,
    StorageProfile,
    StorageState,
)
from app.models.entities import GalleryUploadJob
from app.services import maintenance_service, storage_migration_service as sms, storage_profile_service
from app.services.maintenance_estimator import estimate_storage_migration

_logger = logging.getLogger("hocx.storage_worker")

JOB_NAME = "storage_migration_worker"
LEASE_SECONDS = 60
POLL_SECONDS = float(os.environ.get("STORAGE_WORKER_POLL_SECONDS", "5"))
BATCH_SIZE = 200
MAX_RUN_ATTEMPTS = 10
CUTOVER_LOCK_TIMEOUT = "20s"
# Höchstzahl abgebrochener Cutover-Versuche, danach endet die Migration in "failed" (Quelle aktiv).
MAX_CUTOVER_ATTEMPTS = 5
# Fehlgeschlagene Healthchecks in Folge, ab denen observing in rollback_required wechselt.
OBSERVE_MAX_FAILURES = 3
GALLERY_DRAIN_TIMEOUT_SECONDS = 15 * 60
THROUGHPUT_SAMPLE_SECONDS = 10
CATCHUP_LAG_READY = 50
NAMESPACES = ("main", "abgabebox")


class LeaseLost(Exception):
    """Ein anderer Worker oder ein Admin hat die Migration übernommen."""


class PhaseWait(Exception):
    """Phase wartet auf etwas Externes (Bestätigung, Backoff) - Lease abgeben, später weiter."""

    def __init__(self, seconds: float = POLL_SECONDS) -> None:
        super().__init__("wait")
        self.seconds = seconds


def backoff_seconds(attempt: int, *, base: float = 2.0, cap: float = 600.0) -> float:
    """Exponentielles Backoff mit vollem Jitter (AWS-Empfehlung)."""
    return random.uniform(0, min(cap, base * (2 ** max(0, attempt - 1))))


# --- Lease ------------------------------------------------------------------------------------


@dataclass
class Ctx:
    migration_id: uuid.UUID
    token: int
    owner: str
    lost: threading.Event = field(default_factory=threading.Event)
    stop: threading.Event = field(default_factory=threading.Event)
    limiter: RateLimiter | None = None
    last_sample: float = 0.0

    def check(self) -> None:
        if self.lost.is_set():
            raise LeaseLost()


def claim(owner: str) -> Ctx | None:
    """Übernimmt höchstens eine Migration, deren Lease frei oder abgelaufen ist (SKIP LOCKED -
    zwei Worker können nie dieselbe Migration gleichzeitig halten)."""
    runnable = ", ".join(f"'{state}'" for state in sms.RUNNABLE_STATES)
    with engine.begin() as conn:
        row = conn.execute(text(f"""
            UPDATE storage_migration SET lease_owner = :owner, lease_expires_at = NOW() + make_interval(secs => :lease),
                   fencing_token = fencing_token + 1, heartbeat_at = NOW(), updated_at = NOW()
            WHERE id = (
                SELECT id FROM storage_migration
                WHERE (state IN ({runnable}) OR (cancel_requested AND state NOT IN ('completed', 'failed', 'cancelled', 'cutting_over', 'observing', 'rollback_required')))
                  AND (lease_expires_at IS NULL OR lease_expires_at < NOW())
                  AND (next_attempt_at IS NULL OR next_attempt_at <= NOW() OR cancel_requested)
                ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED)
            RETURNING id, fencing_token
        """), {"owner": owner, "lease": LEASE_SECONDS}).first()
    if row is None:
        return None
    return Ctx(migration_id=row.id, token=row.fencing_token, owner=owner)


def renew(ctx: Ctx) -> bool:
    with engine.begin() as conn:
        result = conn.execute(text("""
            UPDATE storage_migration SET lease_expires_at = NOW() + make_interval(secs => :lease), heartbeat_at = NOW()
            WHERE id = :id AND fencing_token = :token AND lease_owner = :owner
        """), {"id": ctx.migration_id, "token": ctx.token, "owner": ctx.owner, "lease": LEASE_SECONDS})
    return bool(result.rowcount)


def release_lease(ctx: Ctx, *, next_attempt_in: float | None = None) -> None:
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE storage_migration SET lease_owner = NULL, lease_expires_at = NULL,
                   next_attempt_at = CASE WHEN CAST(:delay AS double precision) IS NULL THEN next_attempt_at
                                          ELSE NOW() + make_interval(secs => CAST(:delay AS double precision)) END
            WHERE id = :id AND fencing_token = :token
        """), {"id": ctx.migration_id, "token": ctx.token, "delay": next_attempt_in})


def _heartbeat_loop(ctx: Ctx) -> None:
    while not ctx.stop.wait(LEASE_SECONDS / 4):
        try:
            if not renew(ctx):
                ctx.lost.set()
                return
        except Exception:  # DB kurz weg: Lease läuft notfalls ab, das Fencing schützt die Daten
            _logger.warning("Lease-Verlängerung fehlgeschlagen", exc_info=True)


def guarded(db: Session, ctx: Ctx, **values: Any) -> None:
    """UPDATE der eigenen Migration nur mit gültigem Fencing-Token."""
    values["updated_at"] = datetime.now(UTC)
    result = db.execute(update(StorageMigration).where(StorageMigration.id == ctx.migration_id, StorageMigration.fencing_token == ctx.token).values(**values))
    if not result.rowcount:
        db.rollback()
        raise LeaseLost()


def load(db: Session, ctx: Ctx) -> StorageMigration:
    migration = db.get(StorageMigration, ctx.migration_id)
    if migration is None or migration.fencing_token != ctx.token:
        raise LeaseLost()
    return migration


def move(db: Session, ctx: Ctx, migration: StorageMigration, to_state: str, *, message: str | None = None, level: str = "info", **values: Any) -> None:
    sms.check_transition(migration.state, to_state)
    from_state = migration.state
    guarded(db, ctx, state=to_state, phase_started_at=datetime.now(UTC), **values)
    if to_state in sms.TERMINAL_STATES:
        guarded(db, ctx, finished_at=datetime.now(UTC))
    sms.add_event(db, migration.id, "transition", from_state=from_state, to_state=to_state, message=message, level=level)
    db.commit()
    db.refresh(migration)


def event(db: Session, migration: StorageMigration, kind: str, message: str | None = None, *, level: str = "info", **details: Any) -> None:
    sms.add_event(db, migration.id, kind, level=level, message=message, details=details)
    db.commit()


# --- Backends und Kopieren --------------------------------------------------------------------


def backends(db: Session, migration: StorageMigration) -> tuple[Backend, Backend]:
    source_profile = db.get(StorageProfile, migration.source_profile_id)
    target_profile = db.get(StorageProfile, migration.target_profile_id)
    if source_profile is None or target_profile is None:
        raise sms.MigrationError("Profil fehlt")
    if source_profile.config_version != migration.source_config_version or target_profile.config_version != migration.target_config_version:
        # Szenario 27: ein Profil wurde während der Migration geändert - nie mit geänderter
        # Konfiguration weitermachen (das Profil-API verhindert das zusätzlich).
        raise sms.MigrationError("Quell- oder Zielprofil wurde während der Migration geändert")
    store = get_object_store()
    return (
        store.make_backend(storage_profile_service.profile_config(source_profile, migration.source_generation)),
        store.make_backend(storage_profile_service.profile_config(target_profile, migration.target_generation)),
    )


class _IterReader(io.RawIOBase):
    def __init__(self, chunks: Iterator[bytes], limiter: RateLimiter | None, ctx: Ctx) -> None:
        self._chunks = chunks
        self._buffer = b""
        self._limiter = limiter
        self._ctx = ctx

    def readable(self) -> bool:
        return True

    def read(self, size: int = -1) -> bytes:
        self._ctx.check()  # ein Worker ohne Lease schreibt nicht weiter ins Ziel
        while size < 0 or len(self._buffer) < size:
            chunk = next(self._chunks, None)
            if chunk is None:
                break
            if self._limiter is not None:
                self._limiter.consume(len(chunk))
            self._buffer += chunk
        if size < 0:
            data, self._buffer = self._buffer, b""
        else:
            data, self._buffer = self._buffer[:size], self._buffer[size:]
        return data

    def readinto(self, buffer) -> int:
        data = self.read(len(buffer))
        buffer[: len(data)] = data
        return len(data)


def hash_object(backend: Backend, namespace: str, key: str) -> tuple[str, int]:
    import hashlib

    digest = hashlib.sha256()
    size = 0
    for chunk in backend.open_read(namespace, key):
        digest.update(chunk)
        size += len(chunk)
    return digest.hexdigest(), size


def copy_one(ctx: Ctx, source: Backend, target: Backend, row: dict[str, Any], content_type: str | None) -> tuple[str, int, str]:
    """Kopiert ein Objekt; liefert (Ergebnis, Bytes, sha256). Ergebnis "skipped": Ziel hatte
    bereits genau diesen Stand (Wiederaufnahme nach Absturz)."""
    namespace, key = row["namespace"], row["key"]
    expected_sha, expected_size = row["expected_sha256"], row["expected_size"]
    existing = target.head(namespace, key)
    if existing is not None and expected_sha and existing.size == expected_size and existing.sha256 == expected_sha:
        return "skipped", existing.size, expected_sha
    ctx.check()
    if not expected_sha:
        # Unregistriertes Objekt: SHA vorab berechnen (S3 braucht ihn als Metadatum beim Start).
        with tempfile.TemporaryFile() as spool:
            import hashlib

            digest = hashlib.sha256()
            size = 0
            for chunk in source.open_read(namespace, key):
                spool.write(chunk)
                digest.update(chunk)
                size += len(chunk)
            spool.seek(0)
            sha = digest.hexdigest()
            info = target.put_stream(namespace, key, spool, size=size, sha256=sha, content_type=content_type)
        return "copied", info.size, sha
    info = target.put_stream(
        namespace, key, _IterReader(source.open_read(namespace, key), ctx.limiter, ctx),
        size=expected_size, sha256=expected_sha, content_type=content_type,
    )
    return "copied", info.size, expected_sha


def verify_one(target: Backend, row: dict[str, Any], *, full: bool) -> bool:
    info = target.head(row["namespace"], row["key"])
    if info is None or (row["expected_size"] is not None and info.size != row["expected_size"]):
        return False
    if not full:
        return info.sha256 is None or info.sha256 == row["expected_sha256"]
    sha, size = hash_object(target, row["namespace"], row["key"])
    return sha == row["expected_sha256"] and (row["expected_size"] is None or size == row["expected_size"])


# --- Phasen -----------------------------------------------------------------------------------


def _record_throughput(db: Session, ctx: Ctx, migration: StorageMigration, *, force: bool = False) -> None:
    now = time.time()
    if not force and now - ctx.last_sample < THROUGHPUT_SAMPLE_SECONDS:
        return
    ctx.last_sample = now
    samples = list(migration.throughput or [])[-119:]
    samples.append({"t": now, "bytes": int(migration.copied_bytes or 0), "objects": int(migration.copied_objects or 0)})
    guarded(db, ctx, throughput=samples, checkpoint_at=datetime.now(UTC))
    db.commit()


def _sync_maintenance(db: Session, migration: StorageMigration) -> None:
    """Fortschritt und laufende Schätzung in das zugehörige Wartungsfenster übernehmen."""
    if migration.maintenance_window_id is None:
        return
    scope = "full" if migration.kind == "initial" else "cutover"
    maintenance_service.update_progress(db, migration.maintenance_window_id, progress={
        "phase": migration.state,
        "objects_total": migration.total_objects, "objects_copied": migration.copied_objects,
        "objects_verified": migration.verified_objects, "bytes_total": migration.total_bytes,
        "bytes_copied": migration.copied_bytes,
    }, estimate=estimate_storage_migration(db, migration, scope=scope))
    db.commit()


def _invalid_and_counts(source: Backend, migration: StorageMigration) -> dict[str, Any]:
    """Schnelle Inventur für Preflight/Schätzung (ohne Hashing)."""
    counts = {"objects": 0, "bytes": 0, "excluded_objects": 0, "excluded_bytes": 0, "invalid_keys": []}
    for namespace in NAMESPACES:
        for info in source.list(namespace, ""):
            if info.size < 0:
                counts["invalid_keys"].append(f"{namespace}/{info.key}")
                continue
            if migration.kind == "initial" and sms.is_excluded_initial_key(namespace, info.key):
                counts["excluded_objects"] += 1
                counts["excluded_bytes"] += info.size
                continue
            counts["objects"] += 1
            counts["bytes"] += info.size
    counts["invalid_keys"] = counts["invalid_keys"][:500]
    return counts


def phase_preflight(db: Session, ctx: Ctx, migration: StorageMigration) -> None:
    if migration.state == "pending":
        move(db, ctx, migration, "preflight")
    source, target = backends(db, migration)
    target_profile = db.get(StorageProfile, migration.target_profile_id)
    test = storage_profile_service.run_connection_test(db, target_profile)
    db.commit()
    if not test["ok"]:
        raise StorageUnavailable(f"Verbindungstest zum Ziel fehlgeschlagen: {test.get('error')}")
    for namespace in NAMESPACES:
        if next(iter(target.list(namespace, "")), None) is not None:
            raise sms.MigrationError(f"Zielgeneration g{migration.target_generation} ist nicht leer ({namespace})")
    if migration.kind == "live":
        # Quelle erreichbar? (Liste reicht als Lebenszeichen)
        next(iter(source.list("main", "")), None)
    counts = _invalid_and_counts(source, migration) if migration.kind == "initial" else {
        "objects": int(db.scalar(select(func.count()).select_from(StorageObject).where(StorageObject.status == "active")) or 0),
        "bytes": int(db.scalar(select(func.coalesce(func.sum(StorageObject.size_bytes), 0)).where(StorageObject.status == "active")) or 0),
        "invalid_keys": [],
    }
    if counts["invalid_keys"]:
        raise sms.MigrationError(f"{len(counts['invalid_keys'])} Dateien haben ungültige Namen - siehe Prüfbericht")
    checkpoint = {**(migration.checkpoint or {}), "preflight_inventory": counts}
    guarded(db, ctx, checkpoint=checkpoint)
    db.commit()
    db.refresh(migration)
    estimate = {"full": estimate_storage_migration(db, migration, scope="full")}
    if migration.kind == "live":
        estimate["cutover"] = estimate_storage_migration(db, migration, scope="cutover")
    guarded(db, ctx, estimate=estimate)
    db.commit()
    move(db, ctx, migration, "awaiting_confirmation", message="Preflight bestanden - wartet auf Startbestätigung")


# Ein Galerie-Import, der länger "running" ist, stammt von einem abgebrochenen Prozess (der
# Ingest-Loop setzt solche Jobs beim nächsten Lauf nach der Wartung wieder auf "queued", siehe
# FileService.process_pending_gallery_upload_jobs) - auf ihn zu warten wäre sinnlos.
GALLERY_JOB_STALE_SECONDS = 3 * 60 * 60


def _wait_gallery_jobs(db: Session, migration: StorageMigration, ctx: Ctx) -> None:
    """Laufende Galerie-Importe zu Ende laufen lassen (neue starten in voller Wartung nicht)."""
    deadline = time.monotonic() + GALLERY_DRAIN_TIMEOUT_SECONDS
    while db.scalar(select(func.count()).select_from(GalleryUploadJob).where(
        GalleryUploadJob.status == "running",
        GalleryUploadJob.started_at > datetime.now(UTC) - timedelta(seconds=GALLERY_JOB_STALE_SECONDS),
    )):
        ctx.check()
        if time.monotonic() > deadline:
            raise sms.MigrationError("Laufende Galerie-Importe wurden nicht rechtzeitig fertig")
        db.rollback()
        time.sleep(5)


def fence_storage(db: Session, migration: StorageMigration, reason: str) -> int:
    """Setzt das Schreib-Fence. Wartet (begrenzt) auf alle offenen Schreibtransaktionen, die
    storage_begin_write() aufgerufen haben; neue Schreiber warten bzw. sehen danach das Fence."""
    db.commit()
    db.execute(text(f"SET LOCAL lock_timeout = '{CUTOVER_LOCK_TIMEOUT}'"))
    row = db.execute(text("""
        UPDATE storage_state SET write_fenced = true, fence_reason = :reason, fence_token = fence_token + 1,
               fenced_at = NOW(), updated_at = NOW()
        WHERE id = 1 AND active_profile_id = :profile AND active_generation = :generation
          AND (write_fenced = false OR fence_reason = :reason)
        RETURNING fence_token
    """), {"reason": reason, "profile": migration.source_profile_id, "generation": migration.source_generation}).first()
    if row is None:
        db.rollback()
        raise sms.MigrationError("Aktiver Speicher hat sich geändert oder ist bereits anderweitig gesperrt")
    db.commit()
    get_object_store().invalidate()
    return int(row.fence_token)


def unfence_storage(db: Session, reason: str) -> None:
    db.execute(text("""
        UPDATE storage_state SET write_fenced = false, fence_reason = NULL, fenced_at = NULL, updated_at = NOW()
        WHERE id = 1 AND write_fenced AND fence_reason = :reason
    """), {"reason": reason})
    db.commit()


def fence_reason(migration: StorageMigration) -> str:
    return f"{'initial_migration' if migration.kind == 'initial' else 'cutover'}:{migration.id}"


def phase_prepare_initial(db: Session, ctx: Ctx, migration: StorageMigration) -> None:
    """Erstmigration: volle Wartung aktivieren, laufende Schreibvorgänge abschliessen, fencen."""
    if migration.maintenance_window_id is None:
        window = maintenance_service.create_window(
            db, kind="full", reason_code="storage_initial_migration", state="preparing",
            affected_features=["all"], source_job_type="storage_initial_migration", source_job_id=str(migration.id),
            release_conditions=[{"key": "storage_migration_settled", "params": {"migration_id": str(migration.id)}}, {"key": "storage_not_fenced"}],
            estimate=(migration.estimate or {}).get("full"),
        )
        guarded(db, ctx, maintenance_window_id=window.id)
        db.commit()
        db.refresh(migration)
        event(db, migration, "maintenance_preparing", "Volle Wartung wird vorbereitet")
    # Alle Prozesse übernehmen die Sperre spätestens nach Ablauf ihres Caches; laufende Anfragen
    # bekommen zusätzlich Zeit zum Abschliessen.
    time.sleep(max(2 * settings.maintenance_cache_seconds, 1) + 3)
    _wait_gallery_jobs(db, migration, ctx)
    fence_storage(db, migration, fence_reason(migration))
    window = maintenance_service.lock_window(db, migration.maintenance_window_id)
    if window.state in ("preparing", "failed"):
        maintenance_service.transition(db, window, "active", details={"source": "storage_worker"})
    db.commit()
    event(db, migration, "fenced", "Schreibzugriffe gesperrt, Wartung aktiv")


def phase_inventory(db: Session, ctx: Ctx, migration: StorageMigration) -> None:
    if migration.kind == "initial" and not (migration.checkpoint or {}).get("prepared"):
        phase_prepare_initial(db, ctx, migration)
        guarded(db, ctx, checkpoint={**(migration.checkpoint or {}), "prepared": True})
        db.commit()
        db.refresh(migration)
    source, target = backends(db, migration)
    # Journal-Position zum Zeitpunkt der Inventur: alles danach holt catching_up nach.
    if migration.snapshot_outbox_seq is None:
        snapshot = int(db.scalar(text("SELECT COALESCE(MAX(seq), 0) FROM storage_change_outbox")) or 0)
        guarded(db, ctx, snapshot_outbox_seq=snapshot, applied_outbox_seq=snapshot)
        db.commit()
        db.refresh(migration)
    done = set((migration.checkpoint or {}).get("inventory_done", []))
    report = dict((migration.checkpoint or {}).get("inventory_report") or {"excluded_objects": 0, "excluded_bytes": 0, "unregistered": 0, "registered_missing_in_source": 0})
    for namespace in NAMESPACES:
        if namespace in done:
            continue
        # Register vor der Inventur lesen - auch bei der Erstmigration: ein registriertes Objekt,
        # das in der Quelle fehlt, muss sichtbar werden (sonst bliebe der Cutover später ohne
        # erkennbaren Grund hängen) und lässt sich nur bewusst als fehlend bestätigen.
        registry = {
            row.key: row for row in db.execute(select(StorageObject.key, StorageObject.size_bytes, StorageObject.sha256, StorageObject.version)
                                                .where(StorageObject.namespace == namespace, StorageObject.status == "active")).all()
        }
        # Gelöscht, aber physisch noch nicht entfernt (Tombstone, S3-008): weder kopieren noch
        # wieder als aktiv registrieren - der Purge-Job räumt die Quelle ab.
        tombstones = set(db.scalars(select(StorageObject.key).where(
            StorageObject.namespace == namespace, StorageObject.status == "deleted", StorageObject.purge_pending.is_(True))))
        listed: set[str] = set()
        batch: list[dict[str, Any]] = []

        def flush() -> None:
            if not batch:
                return
            db.execute(text("""
                INSERT INTO storage_migration_object (migration_id, namespace, key, expected_size, expected_sha256, expected_version, source_seq)
                SELECT :mid, x.namespace, x.key, x.size, x.sha, x.version, 0
                FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS x(namespace text, key text, size bigint, sha text, version bigint)
                ON CONFLICT (migration_id, namespace, key) DO NOTHING
            """), {"mid": migration.id, "rows": _json(batch)})
            if migration.kind == "initial":
                # Bestand registrieren (Grösse, SHA-256, Generation 0) - Grundlage für Quota,
                # spätere Migrationen und die Endprüfung.
                db.execute(text("""
                    INSERT INTO storage_object (namespace, key, size_bytes, sha256, version, status, generation)
                    SELECT x.namespace, x.key, x.size, x.sha, 1, 'active', :gen
                    FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS x(namespace text, key text, size bigint, sha text, version bigint)
                    ON CONFLICT (namespace, key) DO UPDATE SET size_bytes = EXCLUDED.size_bytes, sha256 = EXCLUDED.sha256,
                        status = 'active', updated_at = NOW()
                    WHERE NOT storage_object.purge_pending
                """), {"rows": _json(batch), "gen": migration.source_generation})
            guarded(db, ctx, heartbeat_at=datetime.now(UTC))
            db.commit()
            batch.clear()
            # Abbruch/Pause auch während der (bei der Erstmigration hashenden) Inventur - sonst
            # griffe ein Notabbruch erst nach einem vollständigen Lesedurchlauf (S3-012).
            _check_interrupts(db, ctx, migration)

        for info in source.list(namespace, ""):
            ctx.check()
            if info.size < 0:
                raise sms.MigrationError(f"Ungültiger Dateiname: {namespace}/{info.key}")
            if is_internal_key(info.key):
                # Backup-Hold, Restore-Staging, Verbindungstests: nie fachliche Objekte, werden
                # nicht migriert (ein Backup-Hold gehört zur Quellgeneration).
                continue
            if migration.kind == "initial" and sms.is_excluded_initial_key(namespace, info.key):
                report["excluded_objects"] += 1
                report["excluded_bytes"] += info.size
                continue
            if info.key in tombstones:
                continue
            listed.add(info.key)
            if migration.kind == "initial":
                sha, size = hash_object(source, namespace, info.key)
                batch.append({"namespace": namespace, "key": info.key, "size": size, "sha": sha, "version": 1})
            else:
                reg = registry.get(info.key)
                if reg is None:
                    report["unregistered"] += 1  # wird kopiert und registriert, nie ignoriert
                batch.append({"namespace": namespace, "key": info.key, "size": reg.size_bytes if reg else info.size,
                              "sha": reg.sha256 if reg else None, "version": reg.version if reg else None})
            if len(batch) >= BATCH_SIZE:
                flush()
        flush()
        # Registriert, aber in der Quelle nicht auffindbar: als Objekt aufnehmen, der
        # Kopierversuch meldet es dann als fehlend (vorbestehende Inkonsistenz).
        for key in sorted(set(registry) - listed):
            if migration.kind == "initial" and sms.is_excluded_initial_key(namespace, key):
                continue
            report["registered_missing_in_source"] += 1
            reg = registry[key]
            batch.append({"namespace": namespace, "key": key, "size": reg.size_bytes, "sha": reg.sha256, "version": reg.version})
            if len(batch) >= BATCH_SIZE:
                flush()
        flush()
        done.add(namespace)
        guarded(db, ctx, checkpoint={**(migration.checkpoint or {}), "inventory_done": sorted(done), "inventory_report": report})
        db.commit()
        db.refresh(migration)
    totals = db.execute(select(func.count(), func.coalesce(func.sum(StorageMigrationObject.expected_size), 0))
                        .where(StorageMigrationObject.migration_id == migration.id)).one()
    guarded(db, ctx, total_objects=int(totals[0]), total_bytes=int(totals[1]))
    db.commit()
    db.refresh(migration)
    for namespace in NAMESPACES:
        target.abort_stale_multipart_uploads(namespace, 3600)
    checkpoint = {**(migration.checkpoint or {}), "copy_started_at": time.time()}
    move(db, ctx, migration, "copying", checkpoint=checkpoint, message=f"Inventur: {totals[0]} Objekte")


def _json(rows: list[dict[str, Any]]) -> str:
    import json

    return json.dumps(rows)


def _content_types(db: Session, rows: list[dict[str, Any]]) -> dict[tuple[str, str], str | None]:
    if not rows:
        return {}
    keys = {(row["namespace"], row["key"]) for row in rows}
    result = db.execute(select(StorageObject.namespace, StorageObject.key, StorageObject.content_type)
                        .where(StorageObject.key.in_([k for _, k in keys]))).all()
    return {(ns, key): ctype for ns, key, ctype in result if (ns, key) in keys}


def copy_pending(db: Session, ctx: Ctx, migration: StorageMigration) -> bool:
    """Arbeitet einen Stapel offener Objekte ab. Rückgabe False = nichts mehr zu tun."""
    source, target = backends(db, migration)
    rows = [dict(row._mapping) for row in db.execute(
        select(StorageMigrationObject.id, StorageMigrationObject.namespace, StorageMigrationObject.key,
               StorageMigrationObject.expected_size, StorageMigrationObject.expected_sha256, StorageMigrationObject.attempts)
        .where(StorageMigrationObject.migration_id == migration.id,
               StorageMigrationObject.status.in_(("pending", "failed")),
               (StorageMigrationObject.next_attempt_at.is_(None)) | (StorageMigrationObject.next_attempt_at <= datetime.now(UTC)))
        .order_by(StorageMigrationObject.id).limit(BATCH_SIZE)
    ).all()]
    if not rows:
        return False
    content_types = _content_types(db, rows)
    db.commit()
    max_attempts = int((migration.options or {}).get("max_object_attempts", 8))
    throttled = threading.Event()

    def work(row: dict[str, Any]) -> tuple[dict[str, Any], str, int, str | None, str | None]:
        if throttled.is_set():
            return row, "throttled", 0, None, None
        try:
            outcome, size, sha = copy_one(ctx, source, target, row, content_types.get((row["namespace"], row["key"])))
            return row, outcome, size, sha, None
        except LeaseLost:
            raise
        except ObjectNotFound:
            return row, "missing", 0, None, "source_missing"
        except StorageThrottled as exc:
            throttled.set()
            return row, "throttled", 0, None, str(exc)
        except StorageIntegrityError as exc:
            return row, "integrity", 0, None, str(exc)
        except (StorageError, OSError) as exc:
            return row, "error", 0, None, f"{type(exc).__name__}: {exc}"[:500]

    parallelism = int((migration.options or {}).get("parallelism", 4))
    with ThreadPoolExecutor(max_workers=parallelism) as pool:
        results = list(pool.map(work, rows))
    ctx.check()
    now = datetime.now(UTC)
    copied_objects = copied_bytes = failed = 0
    for row, outcome, size, sha, error in results:
        values: dict[str, Any] = {"updated_at": now}
        if outcome in ("copied", "skipped"):
            values.update(status="copied", copied_at=now, last_error=None, next_attempt_at=None, expected_sha256=sha, expected_size=size)
            copied_objects += 1
            copied_bytes += size
            if migration.kind == "live" and not row["expected_sha256"]:
                # Bisher unregistriert: jetzt mit gemessenem Stand registrieren.
                db.execute(text("""
                    INSERT INTO storage_object (namespace, key, size_bytes, sha256, version, status, generation)
                    VALUES (:ns, :key, :size, :sha, 1, 'active', :gen) ON CONFLICT (namespace, key) DO NOTHING
                """), {"ns": row["namespace"], "key": row["key"], "size": size, "sha": sha, "gen": migration.source_generation})
        elif outcome == "throttled":
            values.update(status="failed", next_attempt_at=now + timedelta(seconds=5 + backoff_seconds(3)), last_error=error or "throttled")
        elif outcome == "missing" and _deleted_since(db, row["namespace"], row["key"]):
            values.update(status="deleted", last_error="deleted_in_source")
        elif outcome == "integrity" and migration.kind == "live" and _refresh_expected(db, migration, row):
            values.update(status="pending", next_attempt_at=None, last_error="source_changed")
        else:
            attempts = row["attempts"] + 1
            dead = attempts >= max_attempts
            values.update(status="dead" if dead else "failed", attempts=attempts, last_error=f"{error or outcome}"[:500],
                          next_attempt_at=None if dead else now + timedelta(seconds=backoff_seconds(attempts)))
            failed += 1
        db.execute(update(StorageMigrationObject).where(StorageMigrationObject.id == row["id"]).values(**values))
    dead_total = int(db.scalar(select(func.count()).select_from(StorageMigrationObject).where(
        StorageMigrationObject.migration_id == migration.id, StorageMigrationObject.status.in_(("dead", "failed")))) or 0)
    guarded(db, ctx, copied_objects=StorageMigration.copied_objects + copied_objects, copied_bytes=StorageMigration.copied_bytes + copied_bytes,
            failed_objects=dead_total, heartbeat_at=now)
    db.commit()
    db.refresh(migration)
    _record_throughput(db, ctx, migration)
    if throttled.is_set():
        # Rate-Limit: der ganze Worker bremst, nicht nur ein Objekt.
        time.sleep(5 + backoff_seconds(3, cap=60))
    return True


def _deleted_since(db: Session, namespace: str, key: str) -> bool:
    status = db.scalar(select(StorageObject.status).where(StorageObject.namespace == namespace, StorageObject.key == key))
    return status == "deleted"


def _refresh_expected(db: Session, migration: StorageMigration, row: dict[str, Any]) -> bool:
    current = db.execute(select(StorageObject.sha256, StorageObject.size_bytes, StorageObject.version)
                         .where(StorageObject.namespace == row["namespace"], StorageObject.key == row["key"])).first()
    if current is None or current.sha256 == row["expected_sha256"]:
        return False
    db.execute(update(StorageMigrationObject).where(StorageMigrationObject.id == row["id"]).values(
        expected_sha256=current.sha256, expected_size=current.size_bytes, expected_version=current.version))
    return True


def apply_journal(db: Session, ctx: Ctx, migration: StorageMigration, *, limit: int = 5000) -> int:
    """Holt Änderungen seit applied_outbox_seq nach. Pro Key gewinnt der jüngste Eintrag; eine
    Löschung entfernt das Objekt im Ziel, damit es nach der Migration nicht wieder auftaucht."""
    _, target = backends(db, migration)
    applied = migration.applied_outbox_seq or 0
    rows = db.execute(text("""
        WITH window_rows AS (
            SELECT seq, namespace, key, op, size_bytes, sha256, version FROM storage_change_outbox
            WHERE seq > :applied ORDER BY seq LIMIT :limit
        )
        SELECT DISTINCT ON (namespace, key) seq, namespace, key, op, size_bytes, sha256, version,
               (SELECT MAX(seq) FROM window_rows) AS max_seq
        FROM window_rows ORDER BY namespace, key, seq DESC
    """), {"applied": applied, "limit": limit}).all()
    if not rows:
        return 0
    for row in rows:
        ctx.check()
        if row.op == "delete":
            target.delete(row.namespace, row.key)
            status = "deleted"
        else:
            status = "pending"
        db.execute(text("""
            INSERT INTO storage_migration_object (migration_id, namespace, key, expected_size, expected_sha256, expected_version, source_seq, status)
            VALUES (:mid, :ns, :key, :size, :sha, :version, :seq, :status)
            ON CONFLICT (migration_id, namespace, key) DO UPDATE SET
                expected_size = EXCLUDED.expected_size, expected_sha256 = EXCLUDED.expected_sha256,
                expected_version = EXCLUDED.expected_version, source_seq = EXCLUDED.source_seq, status = EXCLUDED.status,
                attempts = 0, next_attempt_at = NULL, last_error = NULL, verified_at = NULL, updated_at = NOW()
            WHERE storage_migration_object.source_seq < EXCLUDED.source_seq
        """), {"mid": migration.id, "ns": row.namespace, "key": row.key, "size": row.size_bytes, "sha": row.sha256,
               "version": row.version, "seq": row.seq, "status": status})
    total = db.execute(select(func.count(), func.coalesce(func.sum(StorageMigrationObject.expected_size), 0))
                       .where(StorageMigrationObject.migration_id == migration.id, StorageMigrationObject.status != "deleted")).one()
    guarded(db, ctx, applied_outbox_seq=int(rows[0].max_seq), total_objects=int(total[0]), total_bytes=int(total[1]))
    db.commit()
    db.refresh(migration)
    return len(rows)


def journal_lag(db: Session, migration: StorageMigration) -> int:
    newest = int(db.scalar(text("SELECT COALESCE(MAX(seq), 0) FROM storage_change_outbox")) or 0)
    return max(0, newest - (migration.applied_outbox_seq or 0))


def verify_pending(db: Session, ctx: Ctx, migration: StorageMigration) -> bool:
    _, target = backends(db, migration)
    rows = [dict(row._mapping) for row in db.execute(
        select(StorageMigrationObject.id, StorageMigrationObject.namespace, StorageMigrationObject.key,
               StorageMigrationObject.expected_size, StorageMigrationObject.expected_sha256, StorageMigrationObject.attempts)
        .where(StorageMigrationObject.migration_id == migration.id, StorageMigrationObject.status == "copied")
        .order_by(StorageMigrationObject.id).limit(BATCH_SIZE)
    ).all()]
    if not rows:
        return False
    db.commit()
    full = (migration.options or {}).get("verify_mode", "full") == "full"
    with ThreadPoolExecutor(max_workers=int((migration.options or {}).get("parallelism", 4))) as pool:
        results = list(pool.map(lambda row: (row, _safe_verify(target, row, full)), rows))
    ctx.check()
    now = datetime.now(UTC)
    verified = 0
    for row, ok in results:
        if ok:
            db.execute(update(StorageMigrationObject).where(StorageMigrationObject.id == row["id"]).values(status="verified", verified_at=now, updated_at=now))
            verified += 1
        else:
            # Abweichung: neu kopieren (zählt als Versuch).
            db.execute(update(StorageMigrationObject).where(StorageMigrationObject.id == row["id"]).values(
                status="pending", attempts=row["attempts"] + 1, last_error="verification_failed", updated_at=now))
    count = int(db.scalar(select(func.count()).select_from(StorageMigrationObject).where(
        StorageMigrationObject.migration_id == migration.id, StorageMigrationObject.status == "verified")) or 0)
    guarded(db, ctx, verified_objects=count, heartbeat_at=now)
    db.commit()
    db.refresh(migration)
    return True


def _safe_verify(target: Backend, row: dict[str, Any], full: bool) -> bool:
    try:
        return verify_one(target, row, full=full)
    except (StorageError, OSError):
        return False


def open_counts(db: Session, migration: StorageMigration) -> dict[str, int]:
    return {status: values["objects"] for status, values in sms.status_counts(db, migration.id).items()}


def run_copy_loop(db: Session, ctx: Ctx, migration: StorageMigration, *, deadline: float | None = None) -> None:
    while copy_pending(db, ctx, migration):
        _sync_maintenance(db, migration)
        _check_interrupts(db, ctx, migration)
        if deadline is not None and time.monotonic() > deadline:
            return


def _check_interrupts(db: Session, ctx: Ctx, migration: StorageMigration) -> None:
    db.refresh(migration)
    if migration.state in sms.NO_INTERRUPT_STATES:
        return
    if migration.cancel_requested:
        raise _CancelRequested()
    if migration.pause_requested:
        raise _PauseRequested()


class _CancelRequested(Exception):
    pass


class _PauseRequested(Exception):
    pass


def phase_copying(db: Session, ctx: Ctx, migration: StorageMigration) -> None:
    run_copy_loop(db, ctx, migration)
    counts = open_counts(db, migration)
    if counts.get("pending") or counts.get("failed"):
        raise PhaseWait(10)  # Backoff einzelner Objekte abwarten
    copy_started = (migration.checkpoint or {}).get("copy_started_at")
    checkpoint = {**(migration.checkpoint or {}), "copy_seconds": (time.time() - copy_started) if copy_started else None}
    _record_throughput(db, ctx, migration, force=True)
    move(db, ctx, migration, "catching_up", checkpoint=checkpoint)


def phase_catching_up(db: Session, ctx: Ctx, migration: StorageMigration) -> None:
    while apply_journal(db, ctx, migration):
        run_copy_loop(db, ctx, migration)
        _check_interrupts(db, ctx, migration)
        if journal_lag(db, migration) <= CATCHUP_LAG_READY:
            break
    run_copy_loop(db, ctx, migration)
    counts = open_counts(db, migration)
    if counts.get("pending") or counts.get("failed"):
        raise PhaseWait(10)
    move(db, ctx, migration, "verifying")


def phase_verifying(db: Session, ctx: Ctx, migration: StorageMigration) -> None:
    while verify_pending(db, ctx, migration):
        _sync_maintenance(db, migration)
        _check_interrupts(db, ctx, migration)
    if apply_journal(db, ctx, migration):
        run_copy_loop(db, ctx, migration)
    counts = open_counts(db, migration)
    if counts.get("pending") or counts.get("failed"):
        move(db, ctx, migration, "copying", message="Nach der Prüfung erneut zu kopierende Objekte")
        return
    if counts.get("copied"):
        return  # nächste Runde prüft die frisch kopierten
    if counts.get("dead"):
        # Dauerhaft fehlgeschlagene Objekte blockieren den Cutover - nie Daten zurücklassen.
        event(db, migration, "dead_objects", f"{counts['dead']} Objekte dauerhaft fehlgeschlagen", level="error")
        guarded(db, ctx, last_error=f"{counts['dead']} Objekte dauerhaft fehlgeschlagen - erneut versuchen oder als fehlend bestätigen")
        db.commit()
        raise PhaseWait(60)
    references = sms.reference_check(db, migration)
    checkpoint = {**(migration.checkpoint or {}), "reference_check": {k: references[k] for k in ("references", "missing_count", "unreferenced_count")}}
    move(db, ctx, migration, "ready_for_cutover", checkpoint=checkpoint, message="Alle Objekte kopiert und geprüft")


def phase_ready(db: Session, ctx: Ctx, migration: StorageMigration) -> None:
    """Hält das Ziel aktuell, bis der Cutover freigegeben ist."""
    if apply_journal(db, ctx, migration):
        run_copy_loop(db, ctx, migration)
        move(db, ctx, migration, "verifying")
        return
    missing_refs = int(((migration.checkpoint or {}).get("reference_check") or {}).get("missing_count") or 0)
    auto = bool((migration.options or {}).get("auto_cutover")) and missing_refs == 0
    if not auto and migration.cutover_confirmed_at is None:
        raise PhaseWait(POLL_SECONDS)
    move(db, ctx, migration, "cutting_over")


def _final_reconcile(db: Session, ctx: Ctx, migration: StorageMigration, target: Backend) -> dict[str, Any]:
    """Nach Fence + vollständigem Journal: Registry (Wahrheit) gegen Ziel abgleichen."""
    checks: dict[str, Any] = {"registry_objects": 0, "recopied": 0, "removed_from_target": 0, "missing": []}
    expected = {
        (row.namespace, row.key): row for row in db.execute(
            select(StorageObject.namespace, StorageObject.key, StorageObject.size_bytes, StorageObject.sha256, StorageObject.status)).all()
    }
    migrated = {
        (row.namespace, row.key): row for row in db.execute(
            select(StorageMigrationObject.id, StorageMigrationObject.namespace, StorageMigrationObject.key, StorageMigrationObject.status,
                   StorageMigrationObject.expected_sha256, StorageMigrationObject.expected_size)
            .where(StorageMigrationObject.migration_id == migration.id)).all()
    }
    for key, reg in expected.items():
        ctx.check()
        if reg.status != "active" or (migration.kind == "initial" and sms.is_excluded_initial_key(*key)):
            continue
        checks["registry_objects"] += 1
        row = migrated.get(key)
        if row is None or row.status != "verified" or row.expected_sha256 != reg.sha256:
            checks["missing"].append(f"{key[0]}/{key[1]}")
    accepted = set((migration.checkpoint or {}).get("accepted_missing") or [])
    checks["missing"] = [item for item in checks["missing"] if item not in accepted]
    # Ziel darf nichts enthalten, was nicht (mehr) existiert - z. B. Kopien inzwischen
    # gelöschter Dateien. Die Zielgeneration gehört ausschliesslich dieser Migration.
    for namespace in NAMESPACES:
        for info in target.list(namespace, ""):
            ctx.check()
            reg = expected.get((namespace, info.key))
            if reg is None or reg.status != "active":
                target.delete(namespace, info.key)
                checks["removed_from_target"] += 1
    return checks


def phase_cutting_over(db: Session, ctx: Ctx, migration: StorageMigration) -> None:
    reason = fence_reason(migration)
    if migration.kind == "live" and migration.maintenance_window_id is None:
        window = maintenance_service.create_window(
            db, kind="partial", block_scope="writes", reason_code="storage_cutover", state="preparing",
            affected_features=["writes", "uploads", "abgabebox"], source_job_type="storage_cutover", source_job_id=str(migration.id),
            release_conditions=[{"key": "storage_not_fenced"}], estimate=estimate_storage_migration(db, migration, scope="cutover"),
        )
        guarded(db, ctx, maintenance_window_id=window.id)
        db.commit()
        db.refresh(migration)
        # Neue Schreibanfragen bekommen ab jetzt 503 statt am Fence zu warten.
        time.sleep(max(2 * settings.maintenance_cache_seconds, 1))
    try:
        fence_storage(db, migration, reason)
        if migration.kind == "live":
            window = maintenance_service.lock_window(db, migration.maintenance_window_id)
            if window.state == "preparing":
                maintenance_service.transition(db, window, "active", details={"source": "storage_worker"})
            db.commit()
        _, target = backends(db, migration)
        # Journal vollständig nachziehen (bei gesetztem Fence kommt nichts mehr dazu).
        while apply_journal(db, ctx, migration):
            pass
        run_copy_loop(db, ctx, migration)
        while verify_pending(db, ctx, migration):
            pass
        counts = open_counts(db, migration)
        if counts.get("pending") or counts.get("failed") or counts.get("dead") or counts.get("copied"):
            raise sms.MigrationError(f"Endabgleich unvollständig: {counts}")
        checks = _final_reconcile(db, ctx, migration, target)
        if checks["missing"]:
            # Selbstheilung (S3-001): Ein Journaleintrag, dessen Transaktion nach einem späteren
            # Eintrag committet hat, kann beim Nachführen übersprungen worden sein. Unter dem
            # Fence ist das Register die Wahrheit und die Quelle eingefroren - die Abweichungen
            # werden darum gezielt erneut kopiert und vollständig geprüft, statt abzubrechen.
            recopied = _replan_from_registry(db, ctx, migration, checks["missing"])
            run_copy_loop(db, ctx, migration)
            while verify_pending(db, ctx, migration):
                pass
            counts = open_counts(db, migration)
            if counts.get("pending") or counts.get("failed") or counts.get("dead") or counts.get("copied"):
                raise sms.MigrationError(f"Endabgleich unvollständig: {counts}")
            checks = _final_reconcile(db, ctx, migration, target)
            checks["recopied"] = recopied
            if recopied:
                event(db, migration, "final_recopied", f"{recopied} Objekte im Endabgleich nachkopiert", level="warning", recopied=recopied)
        if checks["missing"]:
            raise sms.MigrationError(f"{len(checks['missing'])} registrierte Objekte fehlen im Ziel")
        try:
            fallback_days = max(1, int((migration.options or {}).get("fallback_days") or settings.storage_fallback_days))
        except (TypeError, ValueError):
            # Vor der Validierung angelegte Migration mit ungültiger Option: Standardfrist (S3-010).
            fallback_days = max(1, int(settings.storage_fallback_days))
        now = datetime.now(UTC)
        # Atomarer Wechsel: aktiver Speicher, Generationen und Migration in einer Transaktion,
        # abgesichert über Fence-Grund und Fencing-Token.
        switched = db.execute(text("""
            UPDATE storage_state SET active_profile_id = :target, active_generation = :target_gen, write_fenced = false,
                   fence_reason = NULL, fenced_at = NULL, updated_at = NOW()
            WHERE id = 1 AND write_fenced AND fence_reason = :reason AND active_profile_id = :source AND active_generation = :source_gen
        """), {"target": migration.target_profile_id, "target_gen": migration.target_generation, "reason": reason,
               "source": migration.source_profile_id, "source_gen": migration.source_generation})
        if not switched.rowcount:
            raise sms.MigrationError("Speicherzustand hat sich während des Cutovers geändert")
        db.execute(update(StorageGeneration).where(StorageGeneration.generation == migration.source_generation).values(
            status="retained", deactivated_at=now, retain_until=now + timedelta(days=int(fallback_days))))
        db.execute(update(StorageGeneration).where(StorageGeneration.generation == migration.target_generation).values(
            status="active", activated_at=now, object_count=migration.total_objects, total_bytes=migration.total_bytes))
        guarded(db, ctx, state="observing", cutover_committed_at=now, phase_started_at=now,
                report={**(migration.report or {}), "final_checks": checks, "final_integrity_ok": False})
        sms.add_event(db, migration.id, "transition", from_state="cutting_over", to_state="observing", message="Umgeschaltet")
        db.commit()
        db.refresh(migration)
        get_object_store().invalidate()
    except LeaseLost:
        raise
    except Exception as exc:
        db.rollback()
        db.refresh(migration)
        if migration.cutover_committed_at is None:
            # Vor dem Commit: Quelle bleibt aktiv, Fence wieder weg (Erstmigration: Wartung bleibt).
            if migration.kind == "live":
                unfence_storage(db, reason)
            event(db, migration, "cutover_aborted", f"Cutover abgebrochen, Quelle bleibt aktiv: {exc}", level="warning")
            back = "ready_for_cutover" if migration.kind == "live" else "verifying"
            # Cutover-Abbrüche eigens zählen: attempt wird nach jeder erfolgreichen Phase
            # zurückgesetzt und würde einen immer wieder scheiternden Cutover nie begrenzen
            # (jeder Versuch kostet ein Schreibsperre-Fenster).
            aborts = int((migration.checkpoint or {}).get("cutover_aborts") or 0) + 1
            move(db, ctx, migration, back, checkpoint={**(migration.checkpoint or {}), "cutover_aborts": aborts})
            _close_cutover_window(db, migration)
            if aborts >= MAX_CUTOVER_ATTEMPTS:
                raise sms.MigrationError(f"Cutover {aborts}-mal abgebrochen, zuletzt: {exc}") from exc
            # Vorübergehend behandeln: erneuter Versuch mit Backoff.
            raise StorageUnavailable(f"Cutover abgebrochen: {exc}") from exc
        raise
    _close_cutover_window(db, migration)


def _replan_from_registry(db: Session, ctx: Ctx, migration: StorageMigration, missing: list[str]) -> int:
    """Plant registrierte Objekte, die im Ziel fehlen oder abweichen, mit dem Registerstand neu
    ein (nur unter gesetztem Fence aufrufen). Rückgabe: Anzahl neu eingeplanter Objekte."""
    newest_seq = int(db.scalar(text("SELECT COALESCE(MAX(seq), 0) FROM storage_change_outbox")) or 0)
    planned = 0
    for item in missing:
        namespace, key = item.split("/", 1)
        reg = db.execute(select(StorageObject.size_bytes, StorageObject.sha256, StorageObject.version)
                         .where(StorageObject.namespace == namespace, StorageObject.key == key, StorageObject.status == "active")).first()
        if reg is None:
            continue
        db.execute(text("""
            INSERT INTO storage_migration_object (migration_id, namespace, key, expected_size, expected_sha256, expected_version, source_seq, status)
            VALUES (:mid, :ns, :key, :size, :sha, :version, :seq, 'pending')
            ON CONFLICT (migration_id, namespace, key) DO UPDATE SET
                expected_size = EXCLUDED.expected_size, expected_sha256 = EXCLUDED.expected_sha256,
                expected_version = EXCLUDED.expected_version,
                source_seq = GREATEST(storage_migration_object.source_seq, EXCLUDED.source_seq), status = 'pending',
                attempts = 0, next_attempt_at = NULL, last_error = 'final_reconcile', verified_at = NULL, updated_at = NOW()
        """), {"mid": migration.id, "ns": namespace, "key": key, "size": reg.size_bytes, "sha": reg.sha256,
               "version": reg.version, "seq": newest_seq})
        planned += 1
    total = db.execute(select(func.count(), func.coalesce(func.sum(StorageMigrationObject.expected_size), 0))
                       .where(StorageMigrationObject.migration_id == migration.id, StorageMigrationObject.status != "deleted")).one()
    guarded(db, ctx, total_objects=int(total[0]), total_bytes=int(total[1]))
    db.commit()
    db.refresh(migration)
    return planned


def _close_cutover_window(db: Session, migration: StorageMigration) -> None:
    if migration.kind != "live" or migration.maintenance_window_id is None:
        return
    db.refresh(migration)
    try:
        maintenance_service.release(db, migration.maintenance_window_id, actor_email=None, source="job")
        db.commit()
    except maintenance_service.MaintenanceError:
        db.commit()  # Ablehnung steht im Verlauf; der Supervisor/Admin sieht das Fenster weiter
    db.execute(update(StorageMigration).where(StorageMigration.id == migration.id).values(maintenance_window_id=None))
    db.commit()


def phase_observing(db: Session, ctx: Ctx, migration: StorageMigration) -> None:
    """Healthchecks nach dem Umschalten: Stichprobe über den regulären Lesepfad (aktive
    Generation) und ein Schreib-/Lesetest am Ziel. Scheitert die Prüfung mehrmals in Folge ->
    rollback_required (kein automatischer Rückfall auf möglicherweise veraltete Daten). Ein
    einzelner Fehlschlag (kurzer Hänger des Ziels) wird mit Abstand erneut geprüft (S3-002)."""
    health = sms.target_health(db, migration)
    db.commit()
    if not health["active_matches"]:
        _rollback_required(db, ctx, migration, "Aktiver Speicher entspricht nicht dem Ziel")
        return
    observe = int((migration.options or {}).get("observe_seconds", 300))
    streak = int((migration.checkpoint or {}).get("observe_failures") or 0)
    if not health["ok"]:
        streak += 1
        message = f"Healthcheck fehlgeschlagen: {health['failures']} Objekte, Probe {'ok' if health['probe_ok'] else 'fehlgeschlagen'}"
        if streak < OBSERVE_MAX_FAILURES:
            guarded(db, ctx, checkpoint={**(migration.checkpoint or {}), "observe_failures": streak}, last_error=message)
            db.commit()
            event(db, migration, "observe_check_failed", f"{message} - erneute Prüfung ({streak}/{OBSERVE_MAX_FAILURES})", level="warning")
            raise PhaseWait(min(30, observe))
        _rollback_required(db, ctx, migration, message)
        return
    if streak:
        guarded(db, ctx, checkpoint={**(migration.checkpoint or {}), "observe_failures": 0})
        db.commit()
        db.refresh(migration)
    started = migration.phase_started_at or migration.cutover_committed_at or datetime.now(UTC)
    if (datetime.now(UTC) - started).total_seconds() < observe:
        _sync_maintenance(db, migration)
        raise PhaseWait(min(30, observe))
    report = sms.build_report(db, migration)
    report["final_integrity_ok"] = True
    report["final_checks"] = (migration.report or {}).get("final_checks")
    move(db, ctx, migration, "completed", report=report, message="Migration abgeschlossen")
    if migration.maintenance_window_id is not None:
        window = maintenance_service.lock_window(db, migration.maintenance_window_id)
        if window.state in ("active", "overdue"):
            maintenance_service.transition(db, window, "verifying", details={"source": "storage_worker"})
        try:
            maintenance_service.release(db, window.id, actor_email=None, source="job")
        except maintenance_service.MaintenanceError:
            _logger.warning("Wartung konnte nach der Migration nicht freigegeben werden", exc_info=True)
        db.commit()


def _rollback_required(db: Session, ctx: Ctx, migration: StorageMigration, message: str) -> None:
    move(db, ctx, migration, "rollback_required", message=message, level="error", last_error=message)
    if migration.maintenance_window_id is not None:
        window = maintenance_service.lock_window(db, migration.maintenance_window_id)
        if window.state not in maintenance_service.TERMINAL_STATES and window.state != "failed":
            maintenance_service.transition(db, window, "failed", error=message, details={"source": "storage_worker"})
        db.commit()


# --- Abbruch, Pause, Fehler -------------------------------------------------------------------


def handle_cancel(db: Session, ctx: Ctx, migration: StorageMigration) -> None:
    db.refresh(migration)
    unfence_storage(db, fence_reason(migration))
    move(db, ctx, migration, "cancelled", message="Kontrolliert abgebrochen - Quelle bleibt aktiv")
    db.execute(update(StorageGeneration).where(StorageGeneration.generation == migration.target_generation)
               .values(status="abandoned", deactivated_at=datetime.now(UTC)))
    db.commit()
    if migration.maintenance_window_id is not None:
        try:
            maintenance_service.release(db, migration.maintenance_window_id, actor_email=None, source="job")
        except maintenance_service.MaintenanceError:
            _logger.warning("Wartung nach Abbruch nicht freigebbar", exc_info=True)
        db.commit()


def handle_failure(db: Session, ctx: Ctx, migration: StorageMigration, exc: BaseException, *, permanent: bool) -> None:
    db.rollback()
    db.refresh(migration)
    message = f"{type(exc).__name__}: {exc}"[:2000]
    attempt = migration.attempt + 1
    if not permanent and attempt < MAX_RUN_ATTEMPTS and migration.state not in ("retrying",):
        delay = backoff_seconds(attempt, base=5, cap=900)
        move(db, ctx, migration, "retrying", resume_state=migration.state, attempt=attempt, last_error=message,
             next_attempt_at=datetime.now(UTC) + timedelta(seconds=delay), message=message, level="warning")
        return
    if not permanent and attempt < MAX_RUN_ATTEMPTS:
        guarded(db, ctx, attempt=attempt, last_error=message, next_attempt_at=datetime.now(UTC) + timedelta(seconds=backoff_seconds(attempt, base=5, cap=900)))
        db.commit()
        return
    if migration.cutover_committed_at is not None:
        _rollback_required(db, ctx, migration, message)
        return
    # Vor dem Commit endgültig gescheitert: Quelle aktiv lassen, Fence lösen. Eine volle
    # Wartung bleibt gesperrt (failed), bis ein Admin den konsistenten Zustand freigibt.
    unfence_storage(db, fence_reason(migration))
    if migration.state == "retrying":
        guarded(db, ctx, state=migration.resume_state or migration.state)
        db.commit()
        db.refresh(migration)
    move(db, ctx, migration, "failed", last_error=message, message=message, level="error")
    db.execute(update(StorageGeneration).where(StorageGeneration.generation == migration.target_generation)
               .values(status="abandoned", deactivated_at=datetime.now(UTC)))
    db.commit()
    if migration.maintenance_window_id is not None:
        window = maintenance_service.lock_window(db, migration.maintenance_window_id)
        if window.state not in maintenance_service.TERMINAL_STATES and window.state != "failed":
            maintenance_service.transition(db, window, "failed", error=message, details={"source": "storage_worker"})
        db.commit()


PHASES = {
    "pending": phase_preflight,
    "preflight": phase_preflight,
    "inventory": phase_inventory,
    "copying": phase_copying,
    "catching_up": phase_catching_up,
    "verifying": phase_verifying,
    "ready_for_cutover": phase_ready,
    "cutting_over": phase_cutting_over,
    "observing": phase_observing,
}


def run_migration(ctx: Ctx) -> float | None:
    """Treibt eine Migration so weit wie möglich. Rückgabe: Wartezeit bis zum nächsten Versuch."""
    with SessionLocal() as db:
        migration = load(db, ctx)
        if migration.options.get("bandwidth_limit_mbps"):
            ctx.limiter = RateLimiter(int(float(migration.options["bandwidth_limit_mbps"]) * 1024 * 1024 / 8))
        try:
            if migration.cancel_requested and migration.state not in sms.NO_INTERRUPT_STATES:
                handle_cancel(db, ctx, migration)
                return None
            if migration.state == "retrying":
                move(db, ctx, migration, migration.resume_state or "preflight", resume_state=None)
            # Genau eine Phase je Durchlauf: danach wird die Lease neu beansprucht - so bleibt jede
            # Phase ein klarer, wiederaufnehmbarer Schritt (und ein Admin-Eingriff greift sofort).
            ctx.check()
            if migration.state in sms.TERMINAL_STATES or migration.state in ("awaiting_confirmation", "paused", "rollback_required"):
                return None
            phase = PHASES.get(migration.state)
            if phase is None:
                return None
            if migration.pause_requested and migration.state not in sms.NO_INTERRUPT_STATES:
                raise _PauseRequested()
            phase(db, ctx, migration)
            db.refresh(migration)
            if migration.attempt:
                guarded(db, ctx, attempt=0, last_error=None)
                db.commit()
            return 0.0
        except PhaseWait as wait:
            return wait.seconds
        except _CancelRequested:
            handle_cancel(db, ctx, migration)
        except _PauseRequested:
            db.refresh(migration)
            move(db, ctx, migration, "paused", resume_state=migration.state, pause_requested=False)
        except LeaseLost:
            _logger.warning("Lease für Migration %s verloren - Worker gibt ab", ctx.migration_id)
            raise
        except sms.MigrationError as exc:
            handle_failure(db, ctx, migration, exc, permanent=True)
        except (StorageUnavailable, OperationalError, StorageError, OSError) as exc:
            db.rollback()
            record_system_error(db, exc=exc)
            handle_failure(db, ctx, migration, exc, permanent=False)
        except Exception as exc:
            db.rollback()
            record_system_error(db, exc=exc)
            handle_failure(db, ctx, migration, exc, permanent=False)
    return None


# --- Generationen bereinigen ------------------------------------------------------------------


def purge_generations() -> int:
    """Führt bestätigte Bereinigungen alter Generationen aus (nie automatisch angestossen)."""
    purged = 0
    with SessionLocal() as db:
        # Eine Generation, auf der noch ein Backup-Hold liegt, liest ein laufendes Backup gerade
        # zu Ende (Cutover während des Backups) - erst nach dem Lösen des Holds bereinigen.
        held = db.scalar(select(StorageState.backup_hold_generation).where(StorageState.id == 1))
        query = select(StorageGeneration).where(StorageGeneration.status == "purge_requested")
        if held is not None:
            query = query.where(StorageGeneration.generation != held)
        generation = db.scalars(query.order_by(StorageGeneration.id).limit(1).with_for_update(skip_locked=True)).first()
        if generation is None:
            return 0
        generation.status = "purging"
        db.commit()
        profile = db.get(StorageProfile, generation.profile_id)
        try:
            backend = get_object_store().make_backend(storage_profile_service.profile_config(profile, generation.generation))
            if profile.provider == "filesystem":
                # Nur Dateien, die eine abgeschlossene Erstmigration nachweislich verifiziert hat.
                keys = db.execute(select(StorageMigrationObject.namespace, StorageMigrationObject.key)
                                  .join(StorageMigration, StorageMigration.id == StorageMigrationObject.migration_id)
                                  .where(StorageMigration.source_generation == generation.generation, StorageMigration.state == "completed",
                                         StorageMigrationObject.status == "verified")).all()
                for namespace, key in keys:
                    backend.delete(namespace, key)
                    purged += 1
            else:
                for namespace in NAMESPACES:
                    for info in list(backend.list(namespace, "")):
                        backend.delete(namespace, info.key)
                        purged += 1
                    backend.abort_stale_multipart_uploads(namespace, 0)
            generation.status = "purged"
            generation.purged_at = datetime.now(UTC)
            generation.purge_error = None
        except Exception as exc:
            record_system_error(db, exc=exc)
            generation.status = "purge_requested"
            generation.purge_error = f"{type(exc).__name__}: {exc}"[:2000]
        db.commit()
    return purged


# --- Nach bestätigtem Rollback-Hinweis -------------------------------------------------------

HEALTH_RECHECK_SECONDS = 60


def recheck_failed_cutovers() -> int:
    """Committeter Cutover, Migration nach rollback_required bestätigt (failed), Wartungsfenster
    noch offen: das aktive Ziel regelmässig erneut prüfen. Ein bestandener Healthcheck macht das
    Fenster über storage_migration_settled freigebbar (S3-002) - freigegeben wird nie automatisch."""
    checked = 0
    with SessionLocal() as db:
        candidates = db.scalars(
            select(StorageMigration).join(MaintenanceWindow, MaintenanceWindow.id == StorageMigration.maintenance_window_id)
            .where(StorageMigration.state == "failed", StorageMigration.cutover_committed_at.is_not(None),
                   MaintenanceWindow.state.notin_(maintenance_service.TERMINAL_STATES))
        ).all()
        for migration in candidates:
            health = (migration.report or {}).get("target_health") or {}
            if health.get("ok"):
                continue
            last = health.get("checked_at")
            if last and (datetime.now(UTC) - datetime.fromisoformat(last)).total_seconds() < HEALTH_RECHECK_SECONDS:
                continue
            locked = sms.lock_migration(db, migration.id)
            sms.record_target_health(db, locked)
            db.commit()
            checked += 1
    return checked


# --- Hauptschleife ----------------------------------------------------------------------------


def _heartbeat_job() -> None:
    try:
        with engine.begin() as conn:
            conn.execute(text("SELECT record_job_heartbeat(:job)"), {"job": JOB_NAME})
    except Exception:
        _logger.warning("Job-Heartbeat fehlgeschlagen", exc_info=True)


def run_once(owner: str) -> float:
    """Ein Durchlauf: höchstens eine Migration ein Stück weitertreiben. Für Tests direkt nutzbar."""
    _heartbeat_job()
    purge_generations()
    recheck_failed_cutovers()
    ctx = claim(owner)
    if ctx is None:
        return POLL_SECONDS
    heartbeat = threading.Thread(target=_heartbeat_loop, args=(ctx,), daemon=True)
    heartbeat.start()
    delay: float | None = None
    try:
        delay = run_migration(ctx)
    except LeaseLost:
        delay = POLL_SECONDS
    finally:
        ctx.stop.set()
        heartbeat.join(timeout=5)
        try:
            release_lease(ctx, next_attempt_in=delay if delay and delay > POLL_SECONDS else None)
        except Exception:
            _logger.warning("Lease konnte nicht freigegeben werden (läuft von selbst ab)", exc_info=True)
    return POLL_SECONDS if delay is None else min(delay, POLL_SECONDS)


def configure_tempdir() -> str:
    """Zwischenspeicher (SpooledTemporaryFile ab 16 MiB, TemporaryFile beim Hashen
    unregistrierter Objekte) auf das Platten-Volume STORAGE_WORK_ROOT legen statt nach /tmp: /tmp
    ist im Release ein tmpfs und zählt zum mem_limit des Containers - grosse Objekte bei hoher
    Parallelität führten sonst zum OOM-Kill und zu einer Endlosschleife (S3-005). Die Dateien
    sind unbenannt (O_TMPFILE bzw. sofort gelöscht) und bleiben auch nach einem Absturz nicht liegen."""
    from app.core.storage import storage_work_dir

    path = str(storage_work_dir("storage-worker-tmp"))
    tempfile.tempdir = path
    os.environ["TMPDIR"] = path
    return path


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    configure_tempdir()
    owner = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"
    stopping = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopping.set())
    signal.signal(signal.SIGINT, lambda *_: stopping.set())
    _logger.info("storage-worker %s gestartet", owner)
    while not stopping.is_set():
        try:
            delay = run_once(owner)
        except Exception as exc:  # DB weg o. ä.: protokollieren, weiter versuchen
            _logger.exception("storage-worker: Durchlauf fehlgeschlagen")
            try:
                with SessionLocal() as db:
                    record_system_error(db, exc=exc)
            except Exception:
                pass
            delay = 10
        stopping.wait(delay)


if __name__ == "__main__":
    main()
