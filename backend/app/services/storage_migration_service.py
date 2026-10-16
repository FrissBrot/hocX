"""Storage-Migrationen: Zustandsmaschine, Admin-Aktionen, Berichte (docs-site/docs/technik/storage/migration.md).

Die eigentliche Arbeit macht der Storage-Worker (app/workers/storage_worker.py) in einem eigenen
Container. Dieses Modul enthält alles, was Backend und Worker gemeinsam brauchen:

- MIGRATION_TRANSITIONS: die erlaubten Zustandsübergänge, geprüft bei jeder Änderung.
- Anlegen einer Migration inklusive Generation (eindeutig, unter Advisory-Lock vergeben) und
  den Admin-Aktionen Start, Pause, Fortsetzen, Abbruch, Retry, Cutover bestätigen.
- Referenzprüfung und Prüfbericht.
"""

from __future__ import annotations

import logging
import math
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import (
    DocumentAsset,
    StorageChangeOutbox,
    StorageGeneration,
    StorageMigration,
    StorageMigrationEvent,
    StorageMigrationObject,
    StorageProfile,
    StorageState,
    StoredFile,
    SubmissionUploadFile,
    Tenant,
)
from app.services import storage_profile_service

_logger = logging.getLogger(__name__)

STATES = (
    "pending", "preflight", "awaiting_confirmation", "inventory", "copying", "catching_up", "verifying",
    "ready_for_cutover", "cutting_over", "observing", "completed", "paused", "retrying", "failed",
    "cancelled", "rollback_required",
)
TERMINAL_STATES = ("completed", "failed", "cancelled")
WORK_STATES = ("preflight", "inventory", "copying", "catching_up", "verifying", "ready_for_cutover")
# Zustände, die der Worker aufnimmt (Lease). awaiting_confirmation und paused warten auf Admins.
RUNNABLE_STATES = ("pending", *WORK_STATES, "cutting_over", "observing", "retrying")
# Ab hier darf nicht mehr abgebrochen/pausiert werden: das Umschalten ist im Gang oder erfolgt.
NO_INTERRUPT_STATES = ("cutting_over", "observing", "rollback_required")

MIGRATION_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"preflight", "failed", "cancelled"},
    "preflight": {"awaiting_confirmation", "retrying", "failed", "cancelled"},
    "awaiting_confirmation": {"inventory", "preflight", "cancelled"},
    "inventory": {"copying", "paused", "retrying", "failed", "cancelled"},
    "copying": {"catching_up", "paused", "retrying", "failed", "cancelled"},
    "catching_up": {"verifying", "copying", "paused", "retrying", "failed", "cancelled"},
    "verifying": {"ready_for_cutover", "catching_up", "copying", "paused", "retrying", "failed", "cancelled"},
    "ready_for_cutover": {"cutting_over", "catching_up", "verifying", "paused", "retrying", "failed", "cancelled"},
    # Zurück nach ready_for_cutover/verifying = Cutover vor dem Commit abgebrochen, Quelle bleibt aktiv.
    "cutting_over": {"observing", "ready_for_cutover", "verifying", "retrying", "failed", "rollback_required"},
    "observing": {"completed", "rollback_required"},
    "paused": {"inventory", "copying", "catching_up", "verifying", "ready_for_cutover", "cancelled"},
    "retrying": {"preflight", "inventory", "copying", "catching_up", "verifying", "ready_for_cutover", "cutting_over", "failed", "cancelled", "paused"},
    # Nach einem Commit nur über eine bewusste Admin-Bestätigung bzw. eine neue Migration weiter.
    "rollback_required": {"failed"},
    "completed": set(),
    "failed": set(),
    "cancelled": set(),
}

DEFAULT_OPTIONS = {
    "parallelism": 4,
    "bandwidth_limit_mbps": 0,
    "verify_mode": "full",
    "auto_cutover": False,
    "observe_seconds": 300,
    "fallback_days": None,
    "max_object_attempts": 8,
}

# Ausgeschlossen aus der Erstmigration: temporäre Arbeitsdateien und regenerierbare Caches
# (Namespace "main", relativ zu STORAGE_ROOT). Alles andere wird übernommen - auch unbekannte
# Ordner, die der Prüfbericht dann gesondert ausweist.
INITIAL_EXCLUDED_PREFIXES = (
    "uploads/_staging/",
    "uploads/_multipart/",
    "document_templates/",
    "latex_templates/",
    "abgabebox-uploads/",  # eigener Namespace "abgabebox" (separater Mount)
)
INITIAL_INCLUDED_EXPORT_PREFIX = "exports/generated/"


class MigrationError(ValueError):
    """Erwartete Ablehnung (ValueError-Konvention: kein Eintrag im Fehlerlog)."""


def is_excluded_initial_key(namespace: str, key: str) -> bool:
    if namespace != "main":
        return False
    if key.startswith("exports/") and not key.startswith(INITIAL_INCLUDED_EXPORT_PREFIX):
        return True  # Export-Arbeitsordner
    if "/.hocx-upload-" in f"/{key}" or key.rsplit("/", 1)[-1].startswith(".hocx-upload-"):
        return True
    return any(key.startswith(prefix) for prefix in INITIAL_EXCLUDED_PREFIXES)


def merged_options(options: dict[str, Any] | None, *, kind: str) -> dict[str, Any]:
    merged = dict(DEFAULT_OPTIONS)
    if kind == "initial":
        merged.update({"auto_cutover": True, "observe_seconds": 60})
    for key, value in (options or {}).items():
        if key not in DEFAULT_OPTIONS:
            raise MigrationError(f"Unbekannte Option: {key}")
        merged[key] = value
    merged["parallelism"] = _number(merged["parallelism"], int, "Parallelität")
    if not 1 <= merged["parallelism"] <= 16:
        raise MigrationError("Parallelität muss zwischen 1 und 16 liegen")
    merged["bandwidth_limit_mbps"] = _number(merged["bandwidth_limit_mbps"] or 0, float, "Bandbreite")
    if merged["bandwidth_limit_mbps"] < 0:
        raise MigrationError("Bandbreite darf nicht negativ sein")
    if merged["verify_mode"] not in ("full", "head"):
        raise MigrationError("Ungültiger Prüfmodus")
    if not isinstance(merged["auto_cutover"], bool):
        raise MigrationError("auto_cutover muss true oder false sein")
    merged["observe_seconds"] = max(30, min(_number(merged["observe_seconds"], int, "Beobachtungszeit"), 24 * 3600))
    merged["max_object_attempts"] = max(1, min(_number(merged["max_object_attempts"], int, "Versuche je Objekt"), 50))
    if merged["fallback_days"] is not None:
        # Schutzfrist der alten Generation: nie in der Vergangenheit (sonst sofort bereinigbar).
        merged["fallback_days"] = _number(merged["fallback_days"], int, "Rückfallfrist")
        if not 1 <= merged["fallback_days"] <= 3650:
            raise MigrationError("Rückfallfrist muss zwischen 1 und 3650 Tagen liegen")
    return merged


def _number(value: Any, kind: type, label: str) -> Any:
    """Zahl aus einer Option lesen - Typfehler als erwartete Ablehnung (409), nie als 500 bzw. erst
    im Cutover (S3-010)."""
    if isinstance(value, bool):
        raise MigrationError(f"{label}: Zahl erwartet")
    try:
        number = kind(value)
    except (TypeError, ValueError) as exc:
        raise MigrationError(f"{label}: Zahl erwartet") from exc
    if kind is float and not math.isfinite(number):
        raise MigrationError(f"{label}: Zahl erwartet")
    return number


# --- Ereignisse und Zustandswechsel -----------------------------------------------------------


def add_event(db: Session, migration_id: uuid.UUID, kind: str, *, level: str = "info", message: str | None = None,
              actor_email: str | None = None, from_state: str | None = None, to_state: str | None = None,
              details: dict | None = None) -> None:
    db.add(StorageMigrationEvent(
        migration_id=migration_id, kind=kind, level=level, message=message, actor_email=actor_email,
        from_state=from_state, to_state=to_state, details=details or {},
    ))


def check_transition(from_state: str, to_state: str) -> None:
    if to_state not in MIGRATION_TRANSITIONS.get(from_state, set()):
        raise MigrationError(f"Migration kann nicht von '{from_state}' nach '{to_state}' wechseln")


def admin_transition(db: Session, migration: StorageMigration, to_state: str, *, actor_email: str | None, **values: Any) -> None:
    """Zustandswechsel durch einen Admin (Zeile ist per FOR UPDATE gesperrt). Erhöht das
    Fencing-Token: ein Worker, der die Migration gerade noch hält, kann danach nichts mehr
    schreiben und gibt sie ab."""
    check_transition(migration.state, to_state)
    from_state = migration.state
    migration.state = to_state
    migration.fencing_token += 1
    migration.lease_owner = None
    migration.lease_expires_at = None
    migration.updated_at = datetime.now(UTC)
    migration.phase_started_at = datetime.now(UTC)
    for key, value in values.items():
        setattr(migration, key, value)
    if to_state in TERMINAL_STATES:
        migration.finished_at = datetime.now(UTC)
    add_event(db, migration.id, "transition", actor_email=actor_email, from_state=from_state, to_state=to_state)


def lock_migration(db: Session, migration_id: uuid.UUID) -> StorageMigration:
    migration = db.scalars(select(StorageMigration).where(StorageMigration.id == migration_id).with_for_update()).first()
    if migration is None:
        raise MigrationError("Migration nicht gefunden")
    return migration


# --- Anlegen ----------------------------------------------------------------------------------


def create_migration(db: Session, *, target_profile_id: int, options: dict[str, Any] | None, actor_email: str | None) -> StorageMigration:
    """Neue Migration vom aktiven Speicher zum Zielprofil. Erstmigration (Quelle = Dateisystem)
    oder Live-Migration (Quelle = aktives S3-Profil) wird aus dem aktiven Zustand abgeleitet."""
    # Serialisiert gleichzeitige Anlage-Versuche (zwei Admins, Doppelklick); der Unique-Index
    # uq_storage_migration_open ist die zweite, harte Sicherung.
    db.execute(text("SELECT pg_advisory_xact_lock(202600023)"))
    state = db.get(StorageState, 1)
    if state is None:
        raise MigrationError("Speicherzustand fehlt")
    if state.write_fenced:
        raise MigrationError("Schreibzugriffe sind gerade gesperrt - keine neue Migration möglich")
    open_migration = db.scalar(select(StorageMigration.id).where(StorageMigration.state.notin_(TERMINAL_STATES)).limit(1))
    if open_migration is not None:
        raise MigrationError("Es läuft bereits eine Migration")
    source = db.get(StorageProfile, state.active_profile_id)
    target = db.get(StorageProfile, target_profile_id)
    if source is None or target is None:
        raise MigrationError("Profil nicht gefunden")
    if target.id == source.id:
        raise MigrationError("Quelle und Ziel sind dasselbe Profil")
    if target.provider == "filesystem":
        raise MigrationError("Das Dateisystem kann kein Migrationsziel sein")
    if not target.is_enabled:
        raise MigrationError("Zielprofil ist deaktiviert")
    if not target.last_test_ok:
        raise MigrationError("Zielprofil muss zuerst einen erfolgreichen Verbindungstest bestehen")
    if storage_profile_service.locations_overlap(source, target):
        raise MigrationError("Quelle und Ziel überschneiden sich (gleicher Bucket, überlappender Präfix)")
    kind = "initial" if source.provider == "filesystem" else "live"
    merged = merged_options(options, kind=kind)
    next_generation = int(db.scalar(select(func.coalesce(func.max(StorageGeneration.generation), 0))) or 0) + 1
    migration = StorageMigration(
        kind=kind,
        state="pending",
        source_profile_id=source.id,
        source_generation=state.active_generation,
        source_config_version=source.config_version,
        target_profile_id=target.id,
        target_generation=next_generation,
        target_config_version=target.config_version,
        requested_by_email=actor_email,
        options=merged,
    )
    db.add(migration)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise MigrationError("Es läuft bereits eine Migration") from exc
    db.add(StorageGeneration(profile_id=target.id, generation=next_generation, status="preparing", migration_id=migration.id))
    add_event(db, migration.id, "created", actor_email=actor_email, to_state="pending", details={"kind": kind, "options": merged})
    db.flush()
    return migration


# --- Admin-Aktionen ---------------------------------------------------------------------------


def start(db: Session, migration_id: uuid.UUID, *, actor_email: str | None) -> StorageMigration:
    """Bestätigt den Start nach Preflight und Schätzung. Bei der Erstmigration aktiviert der
    Worker daraufhin die volle Wartung."""
    migration = lock_migration(db, migration_id)
    if migration.state != "awaiting_confirmation":
        raise MigrationError("Migration wartet nicht auf eine Startbestätigung")
    admin_transition(db, migration, "inventory", actor_email=actor_email, start_confirmed_at=datetime.now(UTC),
                     start_confirmed_by=actor_email, started_at=datetime.now(UTC))
    return migration


def pause(db: Session, migration_id: uuid.UUID, *, actor_email: str | None) -> StorageMigration:
    migration = lock_migration(db, migration_id)
    if migration.state in NO_INTERRUPT_STATES or migration.state in TERMINAL_STATES:
        raise MigrationError("Migration kann in diesem Zustand nicht pausiert werden")
    if migration.state == "paused":
        raise MigrationError("Migration ist bereits pausiert")
    if migration.state in ("pending", "preflight", "awaiting_confirmation"):
        raise MigrationError("Vor dem Start gibt es nichts zu pausieren - stattdessen abbrechen")
    resume_state = migration.resume_state if migration.state == "retrying" else migration.state
    admin_transition(db, migration, "paused", actor_email=actor_email, resume_state=resume_state, pause_requested=False)
    return migration


def resume(db: Session, migration_id: uuid.UUID, *, actor_email: str | None) -> StorageMigration:
    migration = lock_migration(db, migration_id)
    if migration.state != "paused":
        raise MigrationError("Migration ist nicht pausiert")
    target_state = migration.resume_state or "copying"
    admin_transition(db, migration, target_state, actor_email=actor_email, resume_state=None, next_attempt_at=None)
    return migration


def cancel(db: Session, migration_id: uuid.UUID, *, actor_email: str | None) -> StorageMigration:
    """Kontrollierter Abbruch vor dem Cutover. Läuft ein Worker, übernimmt er den Abbruch am
    nächsten sicheren Punkt (Fence aufheben, Wartung freigeben); Zieldaten bleiben erhalten
    (Generation 'abandoned', Bereinigung ist ein eigener, bestätigungspflichtiger Schritt)."""
    migration = lock_migration(db, migration_id)
    if migration.state in NO_INTERRUPT_STATES or migration.state in TERMINAL_STATES:
        raise MigrationError("Migration kann in diesem Zustand nicht mehr abgebrochen werden")
    migration.cancel_requested = True
    add_event(db, migration.id, "cancel_requested", actor_email=actor_email)
    worker_active = migration.lease_expires_at is not None and migration.lease_expires_at > datetime.now(UTC)
    # Ohne aktiven Worker und ohne Wartung/Fence (Live-Migration oder Erstmigration vor dem
    # Start) kann sofort abgebrochen werden; sonst räumt der Worker Fence und Wartung auf.
    if not worker_active and (migration.kind == "live" or migration.state in ("pending", "preflight", "awaiting_confirmation")):
        finish_cancel(db, migration, actor_email=actor_email)
    return migration


def finish_cancel(db: Session, migration: StorageMigration, *, actor_email: str | None) -> None:
    admin_transition(db, migration, "cancelled", actor_email=actor_email)
    db.execute(update(StorageGeneration).where(StorageGeneration.generation == migration.target_generation).values(status="abandoned", deactivated_at=datetime.now(UTC)))


def retry_failed(db: Session, migration_id: uuid.UUID, *, actor_email: str | None) -> int:
    migration = lock_migration(db, migration_id)
    if migration.state in TERMINAL_STATES or migration.state in NO_INTERRUPT_STATES:
        raise MigrationError("Migration kann in diesem Zustand keine Objekte erneut versuchen")
    result = db.execute(
        update(StorageMigrationObject)
        .where(StorageMigrationObject.migration_id == migration.id, StorageMigrationObject.status.in_(("failed", "dead")))
        .values(status="pending", attempts=0, next_attempt_at=None, last_error=None, updated_at=datetime.now(UTC))
    )
    migration.failed_objects = 0
    # Zurück zur Kopierphase, damit die wieder offenen Objekte übertragen werden (aus
    # ready_for_cutover über verifying - die Prüfphase leitet bei offenen Objekten weiter).
    if migration.state in ("verifying", "catching_up"):
        admin_transition(db, migration, "copying", actor_email=actor_email)
    elif migration.state == "ready_for_cutover":
        admin_transition(db, migration, "verifying", actor_email=actor_email)
    add_event(db, migration.id, "retry_failed", actor_email=actor_email, details={"objects": result.rowcount or 0})
    return int(result.rowcount or 0)


def accept_missing(db: Session, migration_id: uuid.UUID, *, actor_email: str | None) -> int:
    """Objekte, die schon in der Quelle fehlen (vorbestehende Inkonsistenz), bewusst als fehlend
    bestätigen - sie blockieren sonst den Cutover für immer. Wird im Prüfbericht ausgewiesen."""
    migration = lock_migration(db, migration_id)
    if migration.state in TERMINAL_STATES or migration.state in NO_INTERRUPT_STATES:
        raise MigrationError("Nicht in diesem Zustand")
    rows = db.scalars(select(StorageMigrationObject).where(
        StorageMigrationObject.migration_id == migration.id, StorageMigrationObject.status == "dead",
        StorageMigrationObject.last_error.like("source_missing%"),
    )).all()
    for row in rows:
        row.status = "deleted"
        row.last_error = "accepted_missing_in_source"
        row.updated_at = datetime.now(UTC)
    checkpoint = dict(migration.checkpoint or {})
    checkpoint["accepted_missing"] = sorted({*(checkpoint.get("accepted_missing") or []), *(f"{r.namespace}/{r.key}" for r in rows)})[:5000]
    migration.checkpoint = checkpoint
    add_event(db, migration.id, "accepted_missing", actor_email=actor_email, level="warning", details={"objects": len(rows)})
    return len(rows)


def confirm_cutover(db: Session, migration_id: uuid.UUID, *, actor_email: str | None) -> StorageMigration:
    migration = lock_migration(db, migration_id)
    if migration.state not in ("ready_for_cutover", "verifying", "catching_up"):
        raise MigrationError("Migration ist noch nicht bereit für den Cutover")
    if migration.cutover_confirmed_at is not None:
        raise MigrationError("Cutover wurde bereits bestätigt")
    migration.cutover_confirmed_at = datetime.now(UTC)
    migration.cutover_confirmed_by = actor_email
    add_event(db, migration.id, "cutover_confirmed", actor_email=actor_email)
    return migration


def acknowledge_rollback(db: Session, migration_id: uuid.UUID, *, actor_email: str | None) -> StorageMigration:
    """rollback_required -> failed: der Admin bestätigt, dass er den Zustand gesehen hat. Aktiv
    bleibt das (bereits umgeschaltete) Ziel; zurück geht es nur über eine neue Migration.

    Bei einem committeten Cutover wird das aktive Ziel dabei sofort erneut geprüft (S3-002). Erst
    ein bestandener Healthcheck macht ein noch gesperrtes Wartungsfenster der Erstmigration
    freigebbar; scheitert er, prüft der Storage-Worker regelmässig nach."""
    migration = lock_migration(db, migration_id)
    if migration.state != "rollback_required":
        raise MigrationError("Migration erfordert keinen Rollback")
    admin_transition(db, migration, "failed", actor_email=actor_email)
    if migration.cutover_committed_at is not None:
        record_target_health(db, migration)
    return migration


HEALTH_SAMPLE_SIZE = 25


def target_health(db: Session, migration: StorageMigration) -> dict[str, Any]:
    """Healthcheck des umgeschalteten Ziels über den regulären Lesepfad: aktiver Speicher ist das
    Ziel, eine Stichprobe verifizierter Objekte ist vollständig lesbar (SHA-256), Schreib-/Lesetest
    am Zielprofil. Wird nach dem Cutover (observing) und nach einem bestätigten Rollback genutzt."""
    from app.core.objstore_client import StorageError
    from app.core.storage import get_object_store

    result: dict[str, Any] = {"ok": False, "active_matches": False, "failures": 0, "sampled": 0, "probe_ok": False,
                              "checked_at": datetime.now(UTC).isoformat()}
    store = get_object_store()
    store.invalidate()
    try:
        state = store.active_state(force=True)
    except StorageError as exc:
        result["error"] = f"{type(exc).__name__}"
        return result
    result["active_matches"] = (state.config.profile_id, state.config.generation) == (migration.target_profile_id, migration.target_generation)
    if not result["active_matches"]:
        return result
    sample = db.execute(
        select(StorageMigrationObject.namespace, StorageMigrationObject.key, StorageMigrationObject.expected_sha256, StorageMigrationObject.expected_size)
        .where(StorageMigrationObject.migration_id == migration.id, StorageMigrationObject.status == "verified")
        .order_by(func.random()).limit(HEALTH_SAMPLE_SIZE)
    ).all()
    failures = []
    for row in sample:
        try:
            ok = store.verify(row.namespace, row.key, sha256=row.expected_sha256, size=row.expected_size, full=True)
        except (StorageError, OSError):
            ok = False
        if not ok:
            failures.append(f"{row.namespace}/{row.key}")
    target_profile = db.get(StorageProfile, migration.target_profile_id)
    probe = storage_profile_service.run_connection_test(db, target_profile) if target_profile is not None else {"ok": False}
    result.update(failures=len(failures), failed_keys=failures[:10], sampled=len(sample), probe_ok=bool(probe["ok"]))
    result["ok"] = not failures and bool(probe["ok"])
    return result


def record_target_health(db: Session, migration: StorageMigration) -> dict[str, Any]:
    """Prüft das Ziel und hält das Ergebnis im Bericht fest (Grundlage der Wartungsfreigabe)."""
    health = target_health(db, migration)
    migration.report = {**(migration.report or {}), "target_health": health}
    add_event(db, migration.id, "target_health", level="info" if health["ok"] else "warning",
              message="Ziel nach dem Rollback-Hinweis geprüft: " + ("in Ordnung" if health["ok"] else "weiterhin fehlerhaft"),
              details={k: health[k] for k in ("ok", "active_matches", "failures", "sampled", "probe_ok")})
    db.flush()
    return health


def request_generation_purge(db: Session, generation_id: int, *, confirmation: str, actor_email: str | None) -> StorageGeneration:
    """Löschen einer alten Speichergeneration: separat, bestätigungspflichtig (Eingabe der
    Generationsnummer), nur nach Ablauf der Rückfallfrist bzw. für abgebrochene Ziele."""
    generation = db.scalars(select(StorageGeneration).where(StorageGeneration.id == generation_id).with_for_update()).first()
    if generation is None:
        raise MigrationError("Generation nicht gefunden")
    if confirmation.strip() != f"g{generation.generation}":
        raise MigrationError(f"Zur Bestätigung 'g{generation.generation}' eingeben")
    if generation.status == "active":
        raise MigrationError("Die aktive Generation kann nicht gelöscht werden")
    if generation.status not in ("retained", "abandoned"):
        raise MigrationError("Diese Generation kann nicht (mehr) bereinigt werden")
    if generation.status == "retained" and generation.retain_until and generation.retain_until > datetime.now(UTC):
        raise MigrationError("Die Rückfallfrist dieser Generation läuft noch")
    if db.scalar(select(StorageMigration.id).where(
        StorageMigration.state.notin_(TERMINAL_STATES),
        (StorageMigration.source_generation == generation.generation) | (StorageMigration.target_generation == generation.generation),
    ).limit(1)) is not None:
        raise MigrationError("Generation wird von einer offenen Migration verwendet")
    generation.status = "purge_requested"
    generation.purge_requested_by = actor_email
    generation.purge_requested_at = datetime.now(UTC)
    db.flush()
    return generation


# --- Journal ----------------------------------------------------------------------------------


def purge_deleted_objects(db: Session) -> dict[str, int]:
    """Gelöschte Objekte nach dem Commit physisch entfernen (Tombstones, S3-008), in Batches mit
    eigenem Commit. Bei einem Write-Fence (Cutover/Wartung) endet der Lauf ohne Fehler - der
    nächste Tick macht weiter."""
    from app.core.objstore_client import PURGE_BATCH, StorageWriteFenced
    from app.core.storage import get_object_store

    store = get_object_store()
    purged = 0
    while True:
        try:
            batch = store.purge_deleted(db)
            db.commit()
        except StorageWriteFenced:
            db.rollback()
            break
        purged += batch
        if batch < PURGE_BATCH:
            break
    return {"purged": purged}


def cleanup_journal(db: Session) -> dict[str, int]:
    """Journal-Einträge älter als storage_journal_retention_days löschen - nie solche, die eine
    offene Migration noch nachziehen muss."""
    cutoff = datetime.now(UTC) - timedelta(days=settings.storage_journal_retention_days)
    needed = db.scalar(
        select(func.min(func.coalesce(StorageMigration.applied_outbox_seq, StorageMigration.snapshot_outbox_seq, 0)))
        .where(StorageMigration.state.notin_(TERMINAL_STATES))
    )
    query = StorageChangeOutbox.__table__.delete().where(StorageChangeOutbox.created_at < cutoff)
    if needed is not None:
        query = query.where(StorageChangeOutbox.seq <= needed)
    result = db.execute(query)
    db.commit()
    return {"deleted": int(result.rowcount or 0)}


# --- Referenzen und Bericht -------------------------------------------------------------------


# Erzeugte Exporte: die Aufbewahrung (cleanup_old_generated_exports) entfernt das Objekt und lässt
# die StoredFile-Zeile bewusst stehen (Download liefert dann 404). Eine solche Referenz ohne Objekt
# ist abgelaufen, nicht fehlend - sonst meldete jede Altinstallation "fehlende Dateien", die
# Erstmigration schaltete nie automatisch um und storage_verify bliebe dauerhaft inkonsistent (S3-013).
EXPORT_REFERENCE_KIND = "stored_file_export"


def generated_export_prefix() -> str | None:
    from app.core.storage import key_from_legacy_path

    try:
        return key_from_legacy_path(str(settings.export_root).rstrip("/") + "/generated").rstrip("/") + "/"
    except ValueError:
        return None


def database_references(db: Session) -> dict[tuple[str, str], str]:
    """Alle Dateireferenzen der Datenbank: (namespace, key) -> Art. Snapshot-Präfixe werden als
    "<präfix>/" mit Art "prefix:..." geliefert."""
    from app.core.storage import key_from_legacy_path

    refs: dict[tuple[str, str], str] = {}
    abgabebox_ids = set(db.scalars(select(SubmissionUploadFile.stored_file_id)))
    export_prefix = generated_export_prefix()
    for stored_id, path in db.execute(select(StoredFile.id, StoredFile.storage_path)).all():
        if stored_id in abgabebox_ids:
            refs[("abgabebox", path)] = "stored_file"
        elif export_prefix and path.startswith(export_prefix):
            refs[("main", path)] = EXPORT_REFERENCE_KIND
        else:
            refs[("main", path)] = "stored_file"
    for path in db.scalars(select(Tenant.profile_image_path).where(Tenant.profile_image_path.is_not(None))):
        refs[("main", path)] = "tenant_profile_image"
    # Document Studio: Bilder und Schriften (aus alten Dokumentvorlagen übernommene liegen weiter
    # unter document_template_parts/, siehe Migration 0115/0118).
    for path in db.scalars(select(DocumentAsset.storage_path)):
        try:
            refs[("main", key_from_legacy_path(path))] = "document_asset"
        except ValueError:
            refs[("main", path)] = "document_asset_invalid"
    return refs


def reference_check(db: Session, migration: StorageMigration, *, limit: int = 500) -> dict[str, Any]:
    """Gleicht DB-Referenzen mit den migrierten Objekten ab. fehlende Referenzen = Datei, auf die
    die Datenbank zeigt, die aber nicht verifiziert im Ziel liegt; unreferenziert = Objekt ohne
    Verweis (wird trotzdem übernommen und nie stillschweigend gelöscht)."""
    refs = database_references(db)
    objects = {
        (row.namespace, row.key): row.status
        for row in db.execute(select(StorageMigrationObject.namespace, StorageMigrationObject.key, StorageMigrationObject.status)
                              .where(StorageMigrationObject.migration_id == migration.id)).all()
    }
    present = {key for key, status in objects.items() if status == "verified"}
    # Alle Elternpräfixe vorhandener Objekte ("a/", "a/b/") - macht die Präfixprüfung O(n).
    present_dirs: set[tuple[str, str]] = set()
    for namespace, key in present:
        parts = key.split("/")[:-1]
        for index in range(1, len(parts) + 1):
            present_dirs.add((namespace, "/".join(parts[:index]) + "/"))
    prefix_refs = {(ns, key) for (ns, key), kind in refs.items() if kind.startswith("prefix:")}
    missing: list[dict[str, str]] = []
    expired_exports = 0
    for (namespace, key), kind in refs.items():
        if kind.startswith("prefix:"):
            if (namespace, key) not in present_dirs:
                missing.append({"namespace": namespace, "key": key, "kind": kind})
        elif (namespace, key) not in present:
            status = objects.get((namespace, key), "not_inventoried")
            if kind == EXPORT_REFERENCE_KIND and status == "not_inventoried":
                expired_exports += 1  # schon in der Quelle nicht mehr vorhanden: abgelaufen
                continue
            missing.append({"namespace": namespace, "key": key, "kind": kind, "status": status})

    def under_prefix_ref(namespace: str, key: str) -> bool:
        parts = key.split("/")[:-1]
        return any((namespace, "/".join(parts[:index]) + "/") in prefix_refs for index in range(1, len(parts) + 1))

    unreferenced = [
        {"namespace": ns, "key": key}
        for ns, key in sorted(present)
        if (ns, key) not in refs and not under_prefix_ref(ns, key)
    ]
    return {
        "references": len(refs),
        "missing_count": len(missing),
        "missing": missing[:limit],
        "expired_export_count": expired_exports,
        "unreferenced_count": len(unreferenced),
        "unreferenced": unreferenced[:limit],
    }


def status_counts(db: Session, migration_id: uuid.UUID) -> dict[str, dict[str, int]]:
    rows = db.execute(
        select(StorageMigrationObject.status, func.count(), func.coalesce(func.sum(StorageMigrationObject.expected_size), 0))
        .where(StorageMigrationObject.migration_id == migration_id).group_by(StorageMigrationObject.status)
    ).all()
    return {status: {"objects": int(count), "bytes": int(size)} for status, count, size in rows}


def build_report(db: Session, migration: StorageMigration) -> dict[str, Any]:
    source = db.get(StorageProfile, migration.source_profile_id)
    target = db.get(StorageProfile, migration.target_profile_id)
    failures = db.execute(
        select(StorageMigrationObject.namespace, StorageMigrationObject.key, StorageMigrationObject.status, StorageMigrationObject.last_error, StorageMigrationObject.attempts)
        .where(StorageMigrationObject.migration_id == migration.id, StorageMigrationObject.status.in_(("failed", "dead")))
        .limit(1000)
    ).all()
    return {
        "migration_id": str(migration.id),
        "kind": migration.kind,
        "state": migration.state,
        "generated_at": datetime.now(UTC).isoformat(),
        "source": {"profile": source.name if source else None, "provider": source.provider if source else None, "generation": migration.source_generation},
        "target": {"profile": target.name if target else None, "provider": target.provider if target else None, "generation": migration.target_generation},
        "totals": {
            "objects": migration.total_objects, "bytes": migration.total_bytes, "copied_objects": migration.copied_objects,
            "copied_bytes": migration.copied_bytes, "verified_objects": migration.verified_objects, "failed_objects": migration.failed_objects,
        },
        "status_counts": status_counts(db, migration.id),
        "failures": [{"namespace": r[0], "key": r[1], "status": r[2], "error": r[3], "attempts": r[4]} for r in failures],
        "inventory": (migration.checkpoint or {}).get("inventory_report"),
        "accepted_missing": (migration.checkpoint or {}).get("accepted_missing", []),
        "references": reference_check(db, migration),
        "final_integrity_ok": bool((migration.report or {}).get("final_integrity_ok")),
        "final_checks": (migration.report or {}).get("final_checks"),
    }


def rates(migration: StorageMigration) -> dict[str, Any]:
    from app.services.maintenance_estimator import measured_rates

    current, average = measured_rates(migration)
    remaining = max(0, (migration.total_bytes or 0) - (migration.copied_bytes or 0))
    eta = None
    if remaining and current:
        eta = int(remaining / current)
    return {"current_bps": int(current) if current else None, "average_bps": int(average) if average else None, "remaining_bytes": remaining, "eta_seconds": eta}
