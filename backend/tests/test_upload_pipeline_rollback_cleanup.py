"""Audit MAIN-BE-015: Dateien aus ingest_file verschwinden, wenn der Aufrufer nicht committet."""
import io
from pathlib import Path

import pytest
from PIL import Image

from app.services import upload_pipeline
from tests.factories import make_tenant


@pytest.fixture(autouse=True)
def _isolated_storage_root(monkeypatch, tmp_path):
    from app.core.config import settings

    monkeypatch.setattr(settings, "storage_root", str(tmp_path / "storage"))
    monkeypatch.setattr(settings, "upload_root", str(tmp_path / "storage" / "uploads"))
    monkeypatch.setattr(settings, "thumbnail_root", str(tmp_path / "thumbs"))


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (40, 30), color=(1, 2, 3)).save(buffer, format="PNG")
    return buffer.getvalue()


def _ingest(db, tenant_id: int):
    from app.core.config import settings

    result = upload_pipeline.ingest_file(
        db, tenant_id=tenant_id, content=_png(), original_filename="bild.png", scan_status="clean",
        sniff=upload_pipeline._sniff_image_mime, max_bytes=10 * 1024 * 1024, storage_subdir_parts=("test",),
        enable_perceptual_dedupe=False, enable_thumbnail=True, created_by=None,
    )
    original = Path(settings.storage_root) / result.stored_file.storage_path
    thumbnail = Path(settings.thumbnail_root) / result.stored_file.thumbnail_path
    assert original.exists() and thumbnail.exists()
    return original, thumbnail


def test_rollback_removes_written_files(db):
    tenant = make_tenant(db)
    original, thumbnail = _ingest(db, tenant.id)

    db.rollback()

    assert not original.exists()
    assert not thumbnail.exists()


def test_commit_keeps_written_files(db):
    tenant = make_tenant(db)
    original, thumbnail = _ingest(db, tenant.id)

    db.commit()
    db.rollback()

    assert original.exists()
    assert thumbnail.exists()
