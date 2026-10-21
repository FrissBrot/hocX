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
    return create_engine(_resolve_database_url(), future=True, pool_pre_ping=True, hide_parameters=True)


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


def fetch_files(engine: Engine, stored_file_ids: list[int], *, tenant_id: int | None = None) -> list[dict]:
    """Dateien eines Auftrags. Mit tenant_id nur Dateien dieses Mandanten (Security-Audit SEC-016):
    das Backend füllt stored_file_ids bereits mandantengebunden, der Worker prüft es zusätzlich."""
    if not stored_file_ids:
        return []
    with engine.connect() as conn:
        rows = conn.execute(
            # namespace: Abgabebox-Uploads liegen im eigenen Speicherbereich (siehe objstore_client.py).
            text("""
                SELECT f.id, f.storage_path, f.mime_type,
                       CASE WHEN EXISTS (SELECT 1 FROM submission_upload_file s WHERE s.stored_file_id = f.id)
                            THEN 'abgabebox' ELSE 'main' END AS namespace
                FROM stored_file f WHERE f.id = ANY(:ids) AND (CAST(:tenant_id AS BIGINT) IS NULL OR f.tenant_id = :tenant_id)
            """),
            {"ids": stored_file_ids, "tenant_id": tenant_id},
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


def write_face_quality_scores_batch(engine: Engine, results: list[tuple[int, float | None]]) -> None:
    """Same write as write_face_quality_score, but for every file in a job at once in one
    UPDATE/transaction instead of one connection-checkout+BEGIN/COMMIT cycle per file
    (audit fix, 2026-09-17) - a job can queue up to MAX_ANALYSIS_JOB_IMAGES=2000 files
    (backend/app/services/file_service.py), so _process_job used to cost up to 2000
    separate round trips per job, on the resource-constrained dedicated worker container.
    Explicit ::bigint/::double precision casts on every VALUES row avoid Postgres
    misinferring the score column's type when every file in a job has no detected face
    (score=None for every row, which would otherwise leave nothing typed as float)."""
    if not results:
        return
    # CAST(...) rather than a trailing ::type directly after the bind parameter - some
    # SQLAlchemy text() versions misparse ":name::type" (the adjacent colons), leaving the
    # placeholder un-substituted and sent to Postgres literally.
    values_clause = ", ".join(
        f"(CAST(:id_{i} AS BIGINT), CAST(:score_{i} AS DOUBLE PRECISION))" for i in range(len(results))
    )
    params: dict[str, object] = {}
    for i, (stored_file_id, score) in enumerate(results):
        params[f"id_{i}"] = stored_file_id
        params[f"score_{i}"] = score
    with engine.begin() as conn:
        conn.execute(
            text(
                f"""
                UPDATE stored_file AS sf
                SET face_quality_score = v.score, face_analyzed_at = NOW()
                FROM (VALUES {values_clause}) AS v(id, score)
                WHERE sf.id = v.id
                """
            ),
            params,
        )


def finish_job(engine: Engine, job_id, *, status: str, error: str | None = None) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE photo_analysis_job SET status = :status, finished_at = NOW(), error = :error WHERE id = :id"),
            {"status": status, "error": error, "id": job_id},
        )


# Jobname in backend/app/core/job_registry.py (Übersicht unter /admin/jobs).
JOB_NAME = "photo_analysis_worker"


def record_heartbeat(engine: Engine) -> None:
    """Lebenszeichen aus der Poll-Schleife. Über die SECURITY-DEFINER-Funktion aus Migration
    0105 - hocx_photo_worker hat kein DML auf system_job_status, nur EXECUTE."""
    with engine.begin() as conn:
        conn.execute(text("SELECT record_job_heartbeat(:job_name)"), {"job_name": JOB_NAME})


def record_job_run(engine: Engine, *, status: str, started_at, error: str | None = None) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("SELECT record_job_run(:job_name, :status, :started_at, NOW(), :error, TRUE)"),
            {"job_name": JOB_NAME, "status": status, "started_at": started_at, "error": error},
        )


def full_maintenance_active(engine: Engine) -> bool:
    """Während voller Wartung (z. B. Erstmigration des Speichers) keine Aufträge übernehmen."""
    with engine.connect() as conn:
        return bool(conn.execute(text("SELECT full_active FROM maintenance_effective_state()")).scalar())
