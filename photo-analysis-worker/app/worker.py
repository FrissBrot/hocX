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
from pathlib import Path

from app.db import build_engine, claim_next_job, fetch_files, finish_job, write_face_quality_score
from app.face_quality import load_detector, score_face_quality

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("photo-analysis-worker")

POLL_INTERVAL_SECONDS = float(os.environ.get("PHOTO_WORKER_POLL_INTERVAL_SECONDS", "10"))
MODEL_PATH = os.environ.get("PHOTO_WORKER_MODEL_PATH", "/app/models/face_detection_yunet.onnx")
# Same read-only mount as the value STORAGE_ROOT resolves to on the backend/db - a
# StoredFile.storage_path is always relative to it, see backend's _safe_storage_path.
STORAGE_ROOT = Path(os.environ.get("STORAGE_ROOT", "/app/storage"))


def _process_job(engine, detector, job: dict) -> None:
    stored_file_ids = job["stored_file_ids"]
    logger.info("job %s: processing %d files (tenant %s)", job["id"], len(stored_file_ids), job["tenant_id"])
    files = fetch_files(engine, stored_file_ids)
    scored = 0
    for file_row in files:
        path = STORAGE_ROOT / file_row["storage_path"]
        try:
            image_bytes = path.read_bytes()
        except OSError as exc:
            logger.warning("job %s: could not read %s: %s", job["id"], path, exc)
            continue
        score = score_face_quality(detector, image_bytes)
        write_face_quality_score(engine, file_row["id"], score)
        scored += 1
    logger.info("job %s: scored %d/%d files", job["id"], scored, len(files))
    finish_job(engine, job["id"], status="done")


def run() -> None:
    engine = build_engine()
    detector = load_detector(MODEL_PATH)
    logger.info("photo-analysis-worker started, polling every %ss", POLL_INTERVAL_SECONDS)
    while True:
        job = claim_next_job(engine)
        if job is None:
            time.sleep(POLL_INTERVAL_SECONDS)
            continue
        try:
            _process_job(engine, detector, job)
        except Exception as exc:
            # A single malformed job (bad file on disk, unexpected DB state, ...) must
            # never crash the loop - mark it failed and keep polling for the next one.
            logger.exception("job %s failed", job["id"])
            finish_job(engine, job["id"], status="failed", error=str(exc))


if __name__ == "__main__":
    run()
