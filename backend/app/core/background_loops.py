"""One shared skeleton for every periodic background maintenance loop main.py's lifespan
starts, plus a single ledger of their Postgres advisory-lock ids.

Before this module, each loop hand-rolled the same
while True: with SessionLocal(): pg_try_advisory_lock/finally pg_advisory_unlock/sleep
block with its own copy-pasted lock id literal. That copy-pasting caused a real incident
(2026-09-10): cycle_snapshot_loop's block was copied from protocol_image_rescan_loop and the
lock id was never changed, so the two loops silently shared one lock and starved each other
every tick instead of both running. Collecting every id in BACKGROUND_LOCK_IDS with a
uniqueness assertion below turns that class of bug into an import-time failure instead of a
silent production incident."""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import SessionLocal, engine
from app.core.error_log import record_system_error
from app.core.job_runs import format_job_error, record_job_run

_logger = logging.getLogger(__name__)

_MAX_START_JITTER_SECONDS = 10.0

BACKGROUND_LOCK_IDS: dict[str, int] = {
    "domain_health_check": 202600003,
    "abgabebox_rescan": 202600005,
    # Replaces the three formerly-separate word_import/gallery_upload/protocol_image rescan
    # loops (old ids 202600006/202600008/202600010) - they now share one consolidated sweep,
    # see FileService.rescan_pending_internal_files.
    "upload_pipeline_rescan": 202600006,
    "export_cleanup": 202600007,
    "log_cleanup": 202600009,
    "cycle_snapshot": 202600011,
    # Added for the photo-culling feature (2026-09-17 audit fix) - these three were
    # referenced by main.py's photo_analysis_auto_queue_loop/photo_quality_backfill_loop/
    # photo_album_sync_loop from the moment they were written, but never actually added
    # here, so all three raised KeyError on their very first tick and the entire
    # auto-photo-album feature silently never ran since the 1.1 merge. Any new loop's id
    # MUST be added here the same commit it's referenced in main.py - nothing else checks
    # that the two stay in sync.
    "photo_analysis_auto_queue": 202600012,
    "photo_quality_backfill": 202600013,
    "photo_album_sync": 202600014,
    "gallery_upload_ingest": 202600015,
    "system_monitor": 202600017,
    "task_package_rollover": 202600018,
    "maintenance_supervisor": 202600019,
    "storage_journal_cleanup": 202600020,
    # 202600026 statt 202600023: diese ID hält storage_migration_service.create_migration als
    # Transaktions-Lock (gegenseitiges Blockieren bzw. übersprungene Ticks).
    "document_sync": 202600026,
}

# Lock-IDs anderer Dienste auf derselben Datenbank - Advisory Locks gelten datenbankweit, nicht
# pro Dienst. abgabebox-backend/app/main.py::quarantine_cleanup_loop lief bis 2026-10-11 mit
# 202600007 und hat sich damit Ticks mit export_cleanup geteilt, weil diese Liste nur das Backend
# kannte. Hier eintragen, damit die Eindeutigkeitsprüfung unten auch dienstübergreifend greift.
EXTERNAL_LOCK_IDS: dict[str, int] = {
    "abgabebox_quarantine_cleanup": 202600016,  # abgabebox-backend: QUARANTINE_CLEANUP_LOCK_ID
}

# Einmalige Advisory-Locks (Startup-Seeds, Storage-Worker), damit auch sie in die
# Eindeutigkeitsprüfung eingehen.
RESERVED_LOCK_IDS: dict[str, int] = {
    "startup_seed_data": 202600004,
    "startup_local_storage_profile": 202600021,
    "storage_worker_claim": 202600022,
    "storage_migration_create": 202600023,  # storage_migration_service.create_migration
}

_ALL_LOCK_IDS = [*BACKGROUND_LOCK_IDS.values(), *EXTERNAL_LOCK_IDS.values(), *RESERVED_LOCK_IDS.values()]
assert len(_ALL_LOCK_IDS) == len(set(_ALL_LOCK_IDS)), "duplicate advisory lock id in BACKGROUND_LOCK_IDS/EXTERNAL_LOCK_IDS"


async def run_advisory_locked_loop(
    *,
    name: str,
    interval_seconds: float,
    task: Callable[[Session], object],
    should_run: Callable[[], bool] | None = None,
) -> None:
    """Runs task(db) forever, once per interval_seconds tick, at most once across every
    uvicorn worker (there's no single-instance process in this deployment) - a worker that
    doesn't win the Postgres advisory lock for a given tick just skips it rather than racing
    the worker that did.

    task(db) runs off the event loop via asyncio.to_thread, so a slow or blocking tick (a
    ClamAV scan, a large query, a PIL decode) never stalls this uvicorn worker's request
    handling for its whole duration (2026-09-17 audit fix - previously every tick ran
    in-line on the event loop). A tick that raises is caught, rolled back, and logged
    instead of silently killing the loop forever (also 2026-09-17) - task(db) used to be
    one uncaught exception away from that background job never running again for the
    lifetime of the process, with nothing but an asyncio "exception was never retrieved"
    warning to show for it.

    Guarded by a transaction-scoped Postgres advisory lock (pg_try_advisory_xact_lock) on
    a dedicated connection. A session-scoped pg_try_advisory_lock/pg_advisory_unlock pair
    is unsafe with connection pooling: when task(db) commits or rolls back, its underlying
    connection is returned to the pool, so a subsequent unlock attempt can execute on a
    different connection and silently fail, leaking the lock indefinitely on the pooled
    connection. Transaction scope releases the lock automatically when the dedicated
    connection's transaction ends.

    should_run, if given, is checked before even trying the lock - for a loop that must
    skip a tick entirely rather than acquire-then-no-op (e.g. a low-traffic-window/host-load
    gate that shouldn't fire just because it's due). Optional so callers with no such gate
    don't pay for the extra check.

    name ist der Schlüssel in BACKGROUND_LOCK_IDS und zugleich der Jobname in job_registry.py:
    jeder Tick, der den Lock gewinnt, landet mit Dauer und Ergebnis in system_job_status
    (/admin/jobs). Übersprungene Ticks (should_run False oder Lock bei einem anderen Worker)
    werden bewusst nicht gemeldet - sie sind kein Lauf."""
    # Lazy: job_registry importiert BACKGROUND_LOCK_IDS aus diesem Modul.
    from app.core.job_registry import JOBS_BY_NAME

    from app.services.maintenance_service import current_effective_state

    lock_id = BACKGROUND_LOCK_IDS[name]
    keep_history = JOBS_BY_NAME[name].keep_history
    runs_during_maintenance = JOBS_BY_NAME[name].runs_during_maintenance
    # Startversatz: beim Hochfahren tickten sonst alle Loops im selben Moment, jeder mit
    # Lock-Verbindung + Session - bei 11 Loops 22 Verbindungen für einen Pool von 15. Die
    # Nachzügler warteten bis zum 30-s-Pool-Timeout (2026-10-11 im Dev-Stack gemessen: fast
    # alle ersten Ticks ~30 s, system_monitor bekam gar keine Verbindung).
    await asyncio.sleep(random.uniform(0, min(_MAX_START_JITTER_SECONDS, interval_seconds)))
    def run_tick() -> tuple[str, datetime, datetime, str | None] | None:
        """Ein kompletter Tick inklusive Lock-Verbindung - läuft per asyncio.to_thread
        (Audit MAIN-BE-018): Checkout und Lock-Abfrage liefen vorher synchron auf dem
        Event-Loop und blockierten bei erschöpftem Pool den ganzen Worker bis zum
        Pool-Timeout."""
        # Während voller Wartung pausieren alle nicht ausgenommenen Loops (Tick ohne Meldung,
        # wie ein übersprungener Tick - die Job-Übersicht zeigt die Wartung separat).
        if not runs_during_maintenance and current_effective_state().full_active:
            return None
        if should_run is not None and not should_run():
            return None
        with engine.begin() as lock_conn:
            acquired = lock_conn.execute(
                text("SELECT pg_try_advisory_xact_lock(:lock_id)"),
                {"lock_id": lock_id},
            ).scalar()
            if not acquired:
                return None
            with SessionLocal() as db:
                started_at = datetime.now(timezone.utc)
                try:
                    task(db)
                except Exception as exc:
                    db.rollback()
                    result = ("failure", started_at, datetime.now(timezone.utc), format_job_error(exc))
                    # source defaults to "backend" - system_error_log.source has a
                    # CHECK constraint allowing only "backend"/"abgabebox-backend"
                    # (see SystemErrorLog in app/models/entities.py); "background_loop"
                    # violated it, so every write here silently failed inside
                    # record_system_error's own try/except and never reached the
                    # admin panel (found while auditing why central error logging
                    # "didn't always work").
                    record_system_error(db, exc=exc)
                    return result
                return ("success", started_at, datetime.now(timezone.utc), None)

    while True:
        outcome: tuple[str, datetime, datetime, str | None] | None = None
        try:
            outcome = await asyncio.to_thread(run_tick)
        except Exception as exc:
            # Fehler ausserhalb von task(db) - Lock-Verbindung nicht zu bekommen (Pool erschöpft,
            # DB weg), should_run() wirft, ... Ohne dieses except beendete so ein Fehler den
            # Loop für immer, und zwar lautlos: lifespan() hält die Task-Referenz, also meldet
            # asyncio nicht einmal "exception was never retrieved" (2026-10-11: system_monitor
            # lief im Dev-Stack nach einem Neustart nie). Jetzt zählt das als fehlgeschlagener Tick.
            _logger.exception("Background-Loop %s: Tick ausserhalb der Aufgabe fehlgeschlagen", name)
            now = datetime.now(timezone.utc)
            outcome = ("failure", now, now, format_job_error(exc))
            try:
                with SessionLocal() as error_db:
                    record_system_error(error_db, exc=exc)
            except Exception:
                _logger.exception("Background-Loop %s: Fehler konnte nicht protokolliert werden", name)
        # Erst melden, nachdem Lock-Verbindung und Session zurück im Pool sind: ein Tick hält
        # sonst drei Verbindungen gleichzeitig, und wenn beim Start alle Loops zugleich ticken,
        # warten sie gegenseitig auf den erschöpften Pool (QueuePool-Timeout, 2026-10-11 im
        # Dev-Stack beobachtet).
        if outcome is not None:
            status, started_at, finished_at, error = outcome
            await asyncio.to_thread(
                record_job_run,
                name,
                status=status,
                started_at=started_at,
                finished_at=finished_at,
                error=error,
                keep_history=keep_history,
            )
        await asyncio.sleep(interval_seconds)
