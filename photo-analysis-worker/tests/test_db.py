"""Integration tests for db.py against a real Postgres test DB, exercised through the
worker's own restricted hocx_photo_worker role (build_engine/_resolve_database_url) -
fixture setup/verification goes through the trusted hocx_app role instead (see
conftest.py), since hocx_photo_worker has no INSERT grant at all on stored_file/
photo_analysis_job and only column-level SELECT/UPDATE on stored_file.
"""

from app.db import build_engine, claim_next_job, fetch_files, finish_job, write_face_quality_score


def test_write_face_quality_score_sets_both_the_score_and_face_analyzed_at(make_tenant, make_stored_file, fetch_stored_file):
    tenant_id = make_tenant()
    stored_file_id = make_stored_file(tenant_id)
    engine = build_engine()

    write_face_quality_score(engine, stored_file_id, 7.5)

    row = fetch_stored_file(stored_file_id)
    assert row["face_quality_score"] == 7.5
    assert row["face_analyzed_at"] is not None


def test_write_face_quality_score_with_no_detected_face_still_marks_it_analyzed(make_tenant, make_stored_file, fetch_stored_file):
    """The regression this feature's face_analyzed_at column exists to fix: the detector
    legitimately returns score=None when no face is found, and that must still count as
    "analyzed" - otherwise the backend's off-peak auto-queue (which filters on
    face_analyzed_at IS NULL) re-queues this file forever."""
    tenant_id = make_tenant()
    stored_file_id = make_stored_file(tenant_id)
    engine = build_engine()

    write_face_quality_score(engine, stored_file_id, None)

    row = fetch_stored_file(stored_file_id)
    assert row["face_quality_score"] is None
    assert row["face_analyzed_at"] is not None


def test_fetch_files_returns_only_the_requested_ids_with_the_narrow_column_set(make_tenant, make_stored_file):
    tenant_id = make_tenant()
    id_a = make_stored_file(tenant_id, original_name="a.png", storage_path="uploads/a.png", mime_type="image/png")
    make_stored_file(tenant_id, original_name="b.png")

    rows = fetch_files(build_engine(), [id_a])

    assert [row["id"] for row in rows] == [id_a]
    assert rows[0]["storage_path"] == "uploads/a.png"
    assert rows[0]["mime_type"] == "image/png"


def test_fetch_files_with_no_ids_returns_nothing_without_querying(make_tenant, make_stored_file):
    tenant_id = make_tenant()
    make_stored_file(tenant_id)

    assert fetch_files(build_engine(), []) == []


def test_claim_next_job_picks_the_oldest_queued_job_and_marks_it_running(make_tenant, make_stored_file, make_analysis_job, fetch_analysis_job):
    tenant_id = make_tenant()
    stored_file_id = make_stored_file(tenant_id)
    job_id = make_analysis_job(tenant_id, [stored_file_id], status="queued")

    claimed = claim_next_job(build_engine())

    assert claimed is not None
    assert str(claimed["id"]) == str(job_id)
    row = fetch_analysis_job(job_id)
    assert row["status"] == "running"
    assert row["started_at"] is not None


def test_claim_next_job_ignores_jobs_that_are_not_queued(make_tenant, make_stored_file, make_analysis_job):
    tenant_id = make_tenant()
    stored_file_id = make_stored_file(tenant_id)
    make_analysis_job(tenant_id, [stored_file_id], status="running")
    make_analysis_job(tenant_id, [stored_file_id], status="done")

    assert claim_next_job(build_engine()) is None


def test_finish_job_sets_status_and_error(make_tenant, make_stored_file, make_analysis_job, fetch_analysis_job):
    tenant_id = make_tenant()
    stored_file_id = make_stored_file(tenant_id)
    job_id = make_analysis_job(tenant_id, [stored_file_id], status="running")

    finish_job(build_engine(), job_id, status="failed", error="boom")

    row = fetch_analysis_job(job_id)
    assert row["status"] == "failed"
    assert row["error"] == "boom"
    assert row["finished_at"] is not None
