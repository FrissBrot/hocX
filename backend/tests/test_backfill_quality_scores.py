"""Tests for FileService.backfill_missing_quality_scores - the periodic loop that fills in
sharpness_score/exposure_score for images the abgabebox submission-upload path never
computes them for (see main.py's photo_quality_backfill_loop). Covers the
quality_analyzed_at bounding added in the 2026-09-17 audit fix: a file whose disk content
is missing is stamped as attempted (not just skipped), so it isn't reselected forever."""
from __future__ import annotations

import io

from PIL import Image

from app.models.entities import StoredFile
from app.services.file_service import FileService
from tests.factories import make_tenant

service = FileService()


def _png_bytes(color=(40, 80, 120), size=(48, 48)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color=color).save(buffer, format="PNG")
    return buffer.getvalue()


def _make_pending_stored_file(db, tenant_id, tmp_path, *, write_content: bytes | None) -> StoredFile:
    relative = f"gallery/{len(list(tmp_path.glob('gallery/*'))) if (tmp_path / 'gallery').exists() else 0}.png"
    stored_file = StoredFile(
        tenant_id=tenant_id, original_name="foto.png", mime_type="image/png",
        storage_path=relative, scan_status="clean",
    )
    db.add(stored_file)
    db.flush()
    if write_content is not None:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(write_content)
    return stored_file


def test_backfill_computes_scores_and_stamps_quality_analyzed_at(db, monkeypatch, tmp_path):
    from app.core.config import settings

    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    tenant = make_tenant(db)
    stored_file = _make_pending_stored_file(db, tenant.id, tmp_path, write_content=_png_bytes())

    updated = service.backfill_missing_quality_scores(db)

    assert updated == 1
    db.refresh(stored_file)
    assert stored_file.sharpness_score is not None
    assert stored_file.exposure_score is not None
    assert stored_file.quality_analyzed_at is not None


def test_backfill_stamps_a_file_missing_from_disk_instead_of_leaving_it_pending_forever(db, monkeypatch, tmp_path):
    """Regression test (2026-09-17 audit fix): previously a missing file was `continue`d
    past with both scores left NULL and no marker set, so it matched this method's
    "still missing a score" query on every future tick, forever."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    tenant = make_tenant(db)
    stored_file = _make_pending_stored_file(db, tenant.id, tmp_path, write_content=None)

    updated = service.backfill_missing_quality_scores(db)

    assert updated == 0
    db.refresh(stored_file)
    assert stored_file.sharpness_score is None
    assert stored_file.exposure_score is None
    assert stored_file.quality_analyzed_at is not None

    # A second tick must not re-attempt it - it's already been stamped as looked-at.
    second_pass_updated = service.backfill_missing_quality_scores(db)
    assert second_pass_updated == 0


def test_backfill_ignores_an_already_analyzed_file(db, monkeypatch, tmp_path):
    from app.core.config import settings

    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    tenant = make_tenant(db)
    stored_file = _make_pending_stored_file(db, tenant.id, tmp_path, write_content=_png_bytes())
    service.backfill_missing_quality_scores(db)
    db.refresh(stored_file)
    first_sharpness = stored_file.sharpness_score

    updated = service.backfill_missing_quality_scores(db)

    assert updated == 0
    db.refresh(stored_file)
    assert stored_file.sharpness_score == first_sharpness
