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
from collections.abc import Callable

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import SessionLocal, engine
from app.core.error_log import record_system_error

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
}
assert len(BACKGROUND_LOCK_IDS) == len(set(BACKGROUND_LOCK_IDS.values())), "duplicate background lock id in BACKGROUND_LOCK_IDS"


async def run_advisory_locked_loop(
    *,
    lock_id: int,
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
    don't pay for the extra check."""
    while True:
        if should_run is None or should_run():
            with engine.begin() as lock_conn:
                acquired = lock_conn.execute(
                    text("SELECT pg_try_advisory_xact_lock(:lock_id)"),
                    {"lock_id": lock_id},
                ).scalar()
                if acquired:
                    with SessionLocal() as db:
                        try:
                            await asyncio.to_thread(task, db)
                        except Exception as exc:
                            db.rollback()
                            record_system_error(db, exc=exc, source="background_loop")
        await asyncio.sleep(interval_seconds)
