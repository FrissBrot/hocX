"""Regression tests for upload_pipeline.ingest_file()'s tenant storage-quota enforcement
(audit fix, 2026-09-17) - Tenant.storage_quota_bytes was computed and displayed everywhere
(storage_service.py, the Speicher admin page) but never actually checked by any upload
path before this, so an admin-configured limit had zero effect on whether uploads kept
succeeding."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.repositories.file_repository import StoredFileRepository
from app.services.upload_pipeline import ingest_file
from tests.factories import make_tenant


@pytest.fixture(autouse=True)
def _isolated_storage_root(monkeypatch, tmp_path):
    # Same convention as test_protocol_image_duplicate_check.py - the real stack's
    # storage_root is bind-mounted to the host, writing unmonkeypatched would leave real
    # files behind on disk.
    from app.core.config import settings

    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(settings, "upload_root", str(tmp_path / "uploads"))


def _sniff_anything(content: bytes) -> str | None:
    return "image/png"


def _ingest(db, repo, tenant_id, content: bytes, filename: str):
    return ingest_file(
        db,
        tenant_id=tenant_id,
        content=content,
        original_filename=filename,
        scan_status="clean",
        sniff=_sniff_anything,
        max_bytes=10_000,
        storage_subdir_parts=("tenant-quota-test",),
        enable_perceptual_dedupe=False,
        enable_thumbnail=False,
        created_by=None,
        stored_file_repository=repo,
    )


def test_ingest_file_is_unaffected_when_tenant_has_no_quota_configured(db):
    tenant = make_tenant(db)
    repo = StoredFileRepository()

    result = _ingest(db, repo, tenant.id, b"x" * 100, "a.png")
    db.commit()

    assert result.stored_file.file_size_bytes == 100


def test_ingest_file_rejects_an_upload_that_would_exceed_the_tenant_quota(db):
    tenant = make_tenant(db)
    tenant.storage_quota_bytes = 150
    db.add(tenant)
    db.commit()
    repo = StoredFileRepository()

    _ingest(db, repo, tenant.id, b"x" * 100, "a.png")
    db.commit()
    assert repo.total_bytes_for_tenant(db, tenant.id) == 100

    # No db.rollback() here: ingest_file's quota check runs before any flush/write for the
    # rejected file (see upload_pipeline.py - the check sits above the disk-write/StoredFile
    # section), so the session is left exactly as it was and needs no cleanup; this test
    # fixture's ambient SAVEPOINT-restart rolls back the *entire* test on an explicit
    # rollback, not just this one call (see conftest.db's docstring and the identical note
    # in test_audit_2026_08_12_critical_fixes.py), so asserting DB state afterward requires
    # not calling it here.
    with pytest.raises(HTTPException) as exc_info:
        _ingest(db, repo, tenant.id, b"y" * 100, "b.png")
    assert exc_info.value.status_code == 400

    # The rejected upload must not have counted against usage - no half-written file.
    assert repo.total_bytes_for_tenant(db, tenant.id) == 100


def test_ingest_file_allows_an_upload_that_exactly_fills_the_remaining_quota(db):
    tenant = make_tenant(db)
    tenant.storage_quota_bytes = 100
    db.add(tenant)
    db.commit()
    repo = StoredFileRepository()

    result = _ingest(db, repo, tenant.id, b"x" * 100, "a.png")
    db.commit()

    assert result.stored_file.file_size_bytes == 100
    assert repo.total_bytes_for_tenant(db, tenant.id) == 100


def test_ingest_file_quota_check_is_scoped_per_tenant(db):
    tenant_a = make_tenant(db, "Tenant A")
    tenant_a.storage_quota_bytes = 50
    tenant_b = make_tenant(db, "Tenant B")
    db.add_all([tenant_a, tenant_b])
    db.commit()
    repo = StoredFileRepository()

    # Tenant B has no quota and plenty of usage - must not affect tenant A's check.
    _ingest(db, repo, tenant_b.id, b"z" * 10_000, "big.png")
    db.commit()

    with pytest.raises(HTTPException):
        _ingest(db, repo, tenant_a.id, b"x" * 100, "a.png")
