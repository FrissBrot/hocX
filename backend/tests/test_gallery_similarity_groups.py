"""Integration test for Phase 2 (photo_similarity.py) wired through the real upload
pipeline: FileService.group_similar_gallery_images against StoredFile rows created by an
actual save_gallery_uploads call, so this exercises the real perceptual_hash/sharpness/
exposure values rather than hand-picked ones (see test_photo_similarity.py for the pure
clustering-logic unit tests)."""

import asyncio
import io

import pytest
from PIL import Image, ImageDraw, ImageFilter

from tests.factories import make_tenant
from app.services.file_service import FileService


@pytest.fixture(autouse=True)
def _isolated_storage_root(monkeypatch, tmp_path):
    from app.core.config import settings

    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(settings, "upload_root", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "thumbnail_root", str(tmp_path / "thumbnails"))


def _circle_png_bytes(cx: int, cy: int, r: int, size: tuple[int, int] = (200, 150)) -> bytes:
    """Same helper as test_protocol_image_duplicate_check.py - a flat-color image is a
    degenerate case for pHash, so an actual shape is needed for meaningful similarity."""
    image = Image.new("RGB", size, (20, 20, 20))
    ImageDraw.Draw(image).ellipse([cx - r, cy - r, cx + r, cy + r], fill=(220, 180, 60))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _blurred(content: bytes, radius: float) -> bytes:
    """pHash is deliberately low-frequency/blur-resistant, so a blurred copy of the same
    shot still lands in the same similarity group - exactly the "ten near-identical burst
    shots, pick the sharpest" case this feature exists for."""
    with Image.open(io.BytesIO(content)) as image:
        blurred = image.filter(ImageFilter.GaussianBlur(radius=radius))
        buffer = io.BytesIO()
        blurred.save(buffer, format="PNG")
        return buffer.getvalue()


service = FileService()


def _upload_and_group(db, tenant_id: int, files: list[tuple[str, bytes]]):
    # errors may legitimately contain non-blocking "ähnelt einem bereits hochgeladenen
    # Bild"-Hinweise here (that's the tenant-wide perceptual-hash duplicate warning this
    # test's near-identical burst shots are expected to trigger) - every file still gets
    # stored, which is what `items`'s length asserts below.
    items, _errors = asyncio.run(service.save_gallery_uploads(db, tenant_id=tenant_id, files=files, tags=[], created_by=None))
    assert len(items) == len(files)
    db.commit()
    return service.group_similar_gallery_images(db, tenant_id)


def test_sharp_and_blurred_burst_shot_group_together_with_the_sharp_one_ranked_first(db):
    tenant = make_tenant(db)
    sharp = _circle_png_bytes(100, 75, 50)
    blurred = _blurred(sharp, radius=6)
    different = _circle_png_bytes(40, 110, 45)

    groups = _upload_and_group(
        db,
        tenant.id,
        [("sharp.png", sharp), ("blurred.png", blurred), ("different.png", different)],
    )

    by_size = sorted(groups, key=lambda g: len(g.images))
    assert [len(g.images) for g in by_size] == [1, 2]

    singleton, burst_group = by_size
    assert singleton.images[0].original_name == "different.png"
    assert [image.original_name for image in burst_group.images] == ["sharp.png", "blurred.png"]
    assert burst_group.best_id == burst_group.images[0].id


def test_group_similar_gallery_images_scopes_to_the_given_tenant_only(db):
    tenant_a = make_tenant(db)
    tenant_b = make_tenant(db)
    content = _circle_png_bytes(100, 75, 50)

    asyncio.run(service.save_gallery_uploads(db, tenant_id=tenant_a.id, files=[("a.png", content)], tags=[], created_by=None))
    asyncio.run(service.save_gallery_uploads(db, tenant_id=tenant_b.id, files=[("b.png", content)], tags=[], created_by=None))
    db.commit()

    groups_a = service.group_similar_gallery_images(db, tenant_a.id)

    assert len(groups_a) == 1
    assert [image.original_name for image in groups_a[0].images] == ["a.png"]


def test_min_size_excludes_singleton_groups(db):
    """group_similar_images() legitimately returns a singleton "group" for an image with
    nothing similar to it - the frontend's "Ähnliche" tab only wants actual near-duplicate
    series, so min_size=2 must filter those out (the default min_size=1 keeps today's
    behavior for other callers)."""
    tenant = make_tenant(db)
    sharp = _circle_png_bytes(100, 75, 50)
    blurred = _blurred(sharp, radius=6)
    different = _circle_png_bytes(40, 110, 45)
    items, _errors = asyncio.run(service.save_gallery_uploads(
        db, tenant_id=tenant.id, files=[("sharp.png", sharp), ("blurred.png", blurred), ("different.png", different)], tags=[], created_by=None
    ))
    assert len(items) == 3
    db.commit()

    all_groups = service.group_similar_gallery_images(db, tenant.id, min_size=1)
    assert len(all_groups) == 2

    multi_only = service.group_similar_gallery_images(db, tenant.id, min_size=2)
    assert len(multi_only) == 1
    assert len(multi_only[0].images) == 2


def test_kind_series_groups_more_loosely_than_kind_duplicate(db):
    """"Duplikate" (kind="duplicate", the default) only clusters near-identical re-encodes;
    "Ähnliche" (kind="series") uses the looser SERIES_HAMMING_THRESHOLD so a shifted frame of
    the same scene - not just a re-encode - still lands in the same series. The two shapes
    below have a real perceptual-hash distance of 10 (measured against
    SIMILARITY_HAMMING_THRESHOLD=5 / SERIES_HAMMING_THRESHOLD=14): too far apart for
    "duplicate", close enough for "series". `far` (distance 36 from `base`) stays separate
    under both - the looser threshold must not turn into "group everything"."""
    tenant = make_tenant(db)
    base = _circle_png_bytes(100, 75, 50)
    shifted = _circle_png_bytes(120, 75, 50)
    far = _circle_png_bytes(40, 110, 45)
    items, _errors = asyncio.run(service.save_gallery_uploads(
        db, tenant_id=tenant.id, files=[("base.png", base), ("shifted.png", shifted), ("far.png", far)], tags=[], created_by=None
    ))
    assert len(items) == 3
    db.commit()

    duplicate_groups = service.group_similar_gallery_images(db, tenant.id, kind="duplicate")
    assert sorted(len(g.images) for g in duplicate_groups) == [1, 1, 1]

    series_groups = service.group_similar_gallery_images(db, tenant.id, kind="series")
    by_size = sorted(series_groups, key=lambda g: len(g.images))
    assert [len(g.images) for g in by_size] == [1, 2]
    singleton, series_group = by_size
    assert singleton.images[0].original_name == "far.png"
    assert {image.original_name for image in series_group.images} == {"base.png", "shifted.png"}
