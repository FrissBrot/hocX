"""Thin, purpose-built DB access for the worker - not the full SQLAlchemy ORM setup
backend/ uses (separate build context, and this container only ever touches two tables
through the narrow hocx_photo_worker role - see migration 0067_photo_analysis_job.py).
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import Engine, create_engine, text


def _resolve_database_url() -> str:
    # Same Docker-secrets VAR_FILE convention as backend/app/core/config.py's
    # _load_file_secrets - docker-compose.release.yml mounts the real connection string as
    # a file-based secret rather than a plain env var (a read_only service can't accept
    # Compose environment-secrets at all, see that file's comment).
    if database_url := os.environ.get("PHOTO_WORKER_DATABASE_URL"):
        return database_url
    if path := os.environ.get("PHOTO_WORKER_DATABASE_URL_FILE"):
        return Path(path).read_text(encoding="utf-8").rstrip("\r\n")
    raise RuntimeError("PHOTO_WORKER_DATABASE_URL or PHOTO_WORKER_DATABASE_URL_FILE must be set")


def build_engine() -> Engine:
    return create_engine(_resolve_database_url(), future=True, pool_pre_ping=True)


def claim_next_job(engine: Engine) -> dict | None:
    """Atomically picks the oldest queued job and marks it running, or returns None if
    none is queued. FOR UPDATE SKIP LOCKED means a second worker process (if one were ever
    run) would just move on to the next queued row instead of blocking or double-claiming
    this one - the standard Postgres job-queue pattern, simpler than the advisory-lock
    convention backend/app/main.py's periodic sweeps use since there's no fixed "one loop
    per app instance" shape here to hang a lock namespace off of."""
    with engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT id, tenant_id, stored_file_ids
                FROM photo_analysis_job
                WHERE status = 'queued'
                ORDER BY created_at
                LIMIT 1
                FOR UPDATE SKIP LOCKED
                """
            )
        ).mappings().first()
        if row is None:
            return None
        conn.execute(
            text("UPDATE photo_analysis_job SET status = 'running', started_at = NOW() WHERE id = :id"),
            {"id": row["id"]},
        )
        return dict(row)


def fetch_files(engine: Engine, stored_file_ids: list[int]) -> list[dict]:
    if not stored_file_ids:
        return []
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id, storage_path, mime_type FROM stored_file WHERE id = ANY(:ids)"),
            {"ids": stored_file_ids},
        ).mappings()
        return [dict(row) for row in rows]


def write_face_quality_score(engine: Engine, stored_file_id: int, score: float | None) -> None:
    # face_analyzed_at is set alongside the score even when score is None (no face found) -
    # it's the only way to tell "analyzed, no face" apart from "not analyzed yet", since
    # both leave face_quality_score itself NULL.
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE stored_file SET face_quality_score = :score, face_analyzed_at = NOW() WHERE id = :id"),
            {"score": score, "id": stored_file_id},
        )


def finish_job(engine: Engine, job_id, *, status: str, error: str | None = None) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE photo_analysis_job SET status = :status, finished_at = NOW(), error = :error WHERE id = :id"),
            {"status": status, "error": error, "id": job_id},
        )
