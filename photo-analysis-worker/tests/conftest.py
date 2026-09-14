"""Shared fixtures for db.py/worker.py integration tests.

Fixture setup/verification uses the trusted hocx_app role (full DML on tenant/stored_file)
rather than the worker's own hocx_photo_worker role under test, which only has column-level
SELECT(id, tenant_id, storage_path, mime_type) and UPDATE(face_quality_score,
face_analyzed_at) on stored_file (see backend's migrations 0067/0069) - it can't INSERT a
row to set a test up with at all.
"""

import os

import pytest
from sqlalchemy import create_engine, text


def _admin_database_url() -> str:
    # Same non-secret, fixed local test-only credentials docker-compose.tests.yml's
    # test-migrations service already bakes in (APP_DB_PASSWORD) - not otherwise exposed
    # to this container's env (it only needs PHOTO_WORKER_DATABASE_URL for the app code
    # itself), so tests fall back to the known value rather than requiring new compose
    # wiring just for this.
    return os.environ.get(
        "TEST_ADMIN_DATABASE_URL",
        "postgresql+psycopg://hocx_app:hocx_app_test@test-db:5432/hocx_test",
    )


@pytest.fixture(scope="session")
def admin_engine():
    engine = create_engine(_admin_database_url(), future=True)
    yield engine
    engine.dispose()


@pytest.fixture
def make_tenant(admin_engine):
    def _make(name: str = "Test Tenant") -> int:
        with admin_engine.begin() as conn:
            return conn.execute(text("INSERT INTO tenant (name) VALUES (:name) RETURNING id"), {"name": name}).scalar_one()

    return _make


@pytest.fixture
def make_stored_file(admin_engine):
    def _make(
        tenant_id: int,
        *,
        original_name: str = "bild.png",
        mime_type: str | None = "image/png",
        storage_path: str | None = None,
        face_quality_score: float | None = None,
        face_analyzed_at=None,
    ) -> int:
        path = storage_path or f"uploads/tenant-{tenant_id}/{original_name}"
        with admin_engine.begin() as conn:
            return conn.execute(
                text(
                    "INSERT INTO stored_file "
                    "(tenant_id, original_name, storage_path, mime_type, face_quality_score, face_analyzed_at) "
                    "VALUES (:tenant_id, :original_name, :storage_path, :mime_type, :face_quality_score, :face_analyzed_at) "
                    "RETURNING id"
                ),
                {
                    "tenant_id": tenant_id,
                    "original_name": original_name,
                    "storage_path": path,
                    "mime_type": mime_type,
                    "face_quality_score": face_quality_score,
                    "face_analyzed_at": face_analyzed_at,
                },
            ).scalar_one()

    return _make


@pytest.fixture
def fetch_stored_file(admin_engine):
    def _fetch(stored_file_id: int):
        with admin_engine.begin() as conn:
            return conn.execute(text("SELECT * FROM stored_file WHERE id = :id"), {"id": stored_file_id}).mappings().one()

    return _fetch


@pytest.fixture
def make_analysis_job(admin_engine):
    def _make(tenant_id: int, stored_file_ids: list[int], *, status: str = "queued"):
        import json

        with admin_engine.begin() as conn:
            return conn.execute(
                text(
                    "INSERT INTO photo_analysis_job (tenant_id, stored_file_ids, status) "
                    "VALUES (:tenant_id, CAST(:stored_file_ids AS jsonb), :status) RETURNING id"
                ),
                {"tenant_id": tenant_id, "stored_file_ids": json.dumps(stored_file_ids), "status": status},
            ).scalar_one()

    return _make


@pytest.fixture
def fetch_analysis_job(admin_engine):
    def _fetch(job_id):
        with admin_engine.begin() as conn:
            return conn.execute(text("SELECT * FROM photo_analysis_job WHERE id = :id"), {"id": job_id}).mappings().one()

    return _fetch
