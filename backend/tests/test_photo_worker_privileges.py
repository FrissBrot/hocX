"""Laufzeitrolle hocx_photo_worker: nur die Schreibrechte, die der Foto-Worker braucht
(SECURITY-RULES 2.4; Nachtlauf 2026-11-19, Migration 0197_photo_worker_columns).

0067 gab ``UPDATE`` auf die ganze Tabelle photo_analysis_job - ein übernommener Worker hätte
tenant_id, requested_by oder stored_file_ids eines Auftrags umschreiben können. Der Worker setzt
nur Status, Zeitstempel und Fehler (photo-analysis-worker/app/db.py) und auf stored_file nur das
Gesichtsergebnis."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from tests.factories import make_tenant

ROLE = "hocx_photo_worker"
ALLOWED_UPDATES = {
    "photo_analysis_job": {"status", "started_at", "finished_at", "error"},
    "stored_file": {"face_quality_score", "face_analyzed_at"},
}


def _writable_columns(db, table: str) -> set[str]:
    rows = db.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :table "
            "AND has_column_privilege(:role, format('public.%I', table_name), column_name, 'UPDATE')"
        ),
        {"table": table, "role": ROLE},
    ).scalars()
    return set(rows)


def test_photo_worker_updates_only_the_columns_it_needs(db):
    for table, allowed in ALLOWED_UPDATES.items():
        assert _writable_columns(db, table) == allowed, table


def test_photo_worker_has_no_table_wide_write_privileges(db):
    rows = db.execute(
        text(
            "SELECT table_name, privilege_type FROM information_schema.role_table_grants "
            "WHERE grantee = :role AND privilege_type IN ('INSERT', 'UPDATE', 'DELETE', 'TRUNCATE')"
        ),
        {"role": ROLE},
    ).all()
    assert rows == []


def test_worker_statements_still_work_but_tenant_id_is_protected(db):
    """Die Anweisungen aus photo-analysis-worker/app/db.py laufen unter der Rolle weiter."""
    tenant_id = make_tenant(db, "Worker-Test").id
    job_id = db.scalar(
        text("INSERT INTO photo_analysis_job (tenant_id, stored_file_ids, status) VALUES (:t, '[]', 'queued') RETURNING id"),
        {"t": tenant_id},
    )
    nested = db.begin_nested()
    try:
        db.execute(text(f"SET LOCAL ROLE {ROLE}"))  # sql-ok: feste Rolle
        claimed = db.execute(
            text("SELECT id FROM photo_analysis_job WHERE id = :id FOR UPDATE SKIP LOCKED"), {"id": job_id}
        ).scalar()
        assert claimed == job_id
        db.execute(text("UPDATE photo_analysis_job SET status = 'running', started_at = NOW() WHERE id = :id"), {"id": job_id})
        db.execute(
            text("UPDATE photo_analysis_job SET status = :status, finished_at = NOW(), error = :error WHERE id = :id"),
            {"status": "done", "error": None, "id": job_id},
        )
        inner = db.begin_nested()
        with pytest.raises(ProgrammingError, match="permission denied"):
            db.execute(text("UPDATE photo_analysis_job SET tenant_id = tenant_id WHERE id = :id"), {"id": job_id})
        inner.rollback()
    finally:
        nested.rollback()
