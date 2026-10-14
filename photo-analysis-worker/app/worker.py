"""Phase 3 worker main loop: polls photo_analysis_job for queued jobs, scores each job's
files for face quality, writes results back to stored_file, marks the job done/failed.
Runs as its own container/process (docker-compose.*.yml), not inside backend's asyncio
event loop, since it needs its own resource limits - see db.py for the connection/query
details and face_quality.py for the actual detection+scoring.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from app.db import (
    build_engine,
    claim_next_job,
    fetch_files,
    finish_job,
    full_maintenance_active,
    record_heartbeat,
    record_job_run,
    write_face_quality_scores_batch,
)
from app.objstore_client import ObjectNotFound, ObjectStore, StorageError
from app.face_quality import load_detector, score_face_quality

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("photo-analysis-worker")

POLL_INTERVAL_SECONDS = float(os.environ.get("PHOTO_WORKER_POLL_INTERVAL_SECONDS", "10"))
MODEL_PATH = os.environ.get("PHOTO_WORKER_MODEL_PATH", "/app/models/face_detection_yunet.onnx")
# Dateisystem-Stämme für den bisherigen Bestand (Generation 0); nach der Migration auf S3 liest
# der Worker über das aktive Speicherprofil (objstore_client.py, nur lesend).
STORAGE_ROOT = Path(os.environ.get("STORAGE_ROOT", "/app/storage"))
ABGABEBOX_STORAGE_ROOT = Path(os.environ.get("ABGABEBOX_STORAGE_ROOT", str(STORAGE_ROOT / "abgabebox-uploads")))


def _credentials_key() -> str:
    value = os.environ.get("STORAGE_CREDENTIALS_KEY", "")
    path = os.environ.get("STORAGE_CREDENTIALS_KEY_FILE")
    if not value and path:
        value = Path(path).read_text(encoding="utf-8").strip()
    return value


def build_store(engine) -> ObjectStore:
    return ObjectStore(
        service="photo-worker",
        connect=engine.connect,
        filesystem_roots={"main": STORAGE_ROOT, "abgabebox": ABGABEBOX_STORAGE_ROOT},
        credentials_key=_credentials_key,
    )


def _process_job(engine, detector, job: dict, store: ObjectStore | None = None) -> None:
    store = store or build_store(engine)
    stored_file_ids = job["stored_file_ids"]
    logger.info("job %s: processing %d files (tenant %s)", job["id"], len(stored_file_ids), job["tenant_id"])
    files = fetch_files(engine, stored_file_ids)
    scored = 0
    # Accumulated and written in one batched UPDATE after the loop instead of one
    # transaction per file (audit fix, 2026-09-17 - see write_face_quality_scores_batch).
    results: list[tuple[int, float | None]] = []
    for file_row in files:
        namespace = file_row.get("namespace") or "main"
        try:
            image_bytes = store.get_bytes(namespace, file_row["storage_path"])
        except (ObjectNotFound, StorageError, OSError, ValueError) as exc:
            logger.warning("job %s: could not read %s/%s: %s", job["id"], namespace, file_row["storage_path"], exc)
            # Mark it analyzed anyway (no score) - otherwise a file missing from disk gets
            # re-queued and re-attempted by every future off-peak run, forever.
            results.append((file_row["id"], None))
            continue
        score = score_face_quality(detector, image_bytes)
        results.append((file_row["id"], score))
        scored += 1
    write_face_quality_scores_batch(engine, results)
    logger.info("job %s: scored %d/%d files", job["id"], scored, len(files))
    finish_job(engine, job["id"], status="done")


def _report(fn, *args, **kwargs) -> None:
    """Meldungen an /admin/jobs (Heartbeat, Läufe) sind best effort: scheitern sie, soll die
    Analyse trotzdem weiterlaufen. Dieser Container hat keinen Zugriff auf system_error_log -
    ein dauerhaft fehlendes Lebenszeichen fällt dort stattdessen als überfälliger Worker auf."""
    try:
        fn(*args, **kwargs)
    except Exception:
        logger.warning("job status report failed", exc_info=True)


def run() -> None:
    engine = build_engine()
    detector = load_detector(MODEL_PATH)
    logger.info("photo-analysis-worker started, polling every %ss", POLL_INTERVAL_SECONDS)
    store = build_store(engine)
    while True:
        _report(record_heartbeat, engine)
        try:
            paused = full_maintenance_active(engine)
        except Exception:
            logger.warning("Wartungszustand nicht lesbar - Worker wartet vorsichtshalber", exc_info=True)
            paused = True
        if paused:
            time.sleep(POLL_INTERVAL_SECONDS)
            continue
        job = claim_next_job(engine)
        if job is None:
            time.sleep(POLL_INTERVAL_SECONDS)
            continue
        started_at = datetime.now(timezone.utc)
        try:
            _process_job(engine, detector, job, store)
        except Exception as exc:
            # A single malformed job (bad file on disk, unexpected DB state, ...) must
            # never crash the loop - mark it failed and keep polling for the next one.
            logger.exception("job %s failed", job["id"])
            finish_job(engine, job["id"], status="failed", error=str(exc))
            _report(record_job_run, engine, status="failure", started_at=started_at, error=f"{type(exc).__name__}: {exc}"[:4000])
        else:
            _report(record_job_run, engine, status="success", started_at=started_at)


if __name__ == "__main__":
    run()
