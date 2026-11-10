"""Integration test for Phase 2 (photo_similarity.py) wired through the real upload
pipeline: the job-worker's background grouping (FileService._refresh_tenant_similarity, stored
in photo_similarity_result) and the read path behind the "Duplikate"/"Ähnliche" tabs
(FileService.list_similarity_groups, GET /files/similarity-groups) against StoredFile rows
created by an actual save_gallery_uploads call, so this exercises the real perceptual_hash/
sharpness/exposure values rather than hand-picked ones (see test_photo_similarity.py for the
pure clustering-logic unit tests)."""

import asyncio
import io

import pytest
from PIL import Image, ImageDraw, ImageFilter

from sqlalchemy import select

from tests.factories import make_current_user, make_tenant
from app.api.routes import files as files_routes
from app.models.entities import PhotoSimilarityResult
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


def _reencoded(content: bytes) -> bytes:
    """Dieselbe Aufnahme als verkleinerte JPEG-Kopie - ein echtes Duplikat."""
    with Image.open(io.BytesIO(content)) as image:
        copy = image.convert("RGB").resize((160, 120), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        copy.save(buffer, format="JPEG", quality=80)
        return buffer.getvalue()


service = FileService()


def _upload(db, tenant_id: int, files: list[tuple[str, bytes]]):
    # errors may legitimately contain non-blocking "ähnelt einem bereits hochgeladenen
    # Bild"-Hinweise here (that's the tenant-wide perceptual-hash duplicate warning this
    # test's near-identical burst shots are expected to trigger) - every file still gets
    # stored, which is what `items`'s length asserts below.
    items, _errors = asyncio.run(service.save_gallery_uploads(db, tenant_id=tenant_id, files=files, tags=[], created_by=None))
    assert len(items) == len(files)
    db.commit()
    return items


def _names(result):
    return sorted(sorted(image.original_name for image in group.images) for group in result.groups)


def test_tabs_report_pending_until_the_background_job_has_grouped_the_tenant(db):
    tenant = make_tenant(db)
    sharp = _circle_png_bytes(100, 75, 50)
    _upload(db, tenant.id, [("sharp.png", sharp), ("blurred.png", _reencoded(sharp))])

    pending = service.list_similarity_groups(db, tenant.id, kind="duplicate")
    assert pending.status == "pending"
    assert pending.groups == []

    service._refresh_tenant_similarity(db, tenant.id)
    ready = service.list_similarity_groups(db, tenant.id, kind="duplicate")
    assert ready.status == "ready"
    assert ready.computed_at is not None
    assert len(ready.groups) == 1


def test_sharp_and_blurred_burst_shot_are_a_series_not_a_duplicate(db):
    """Ein unscharfes Serienbild ist eine andere Aufnahme: es erscheint unter «Ähnliche»
    (schärferes zuerst), nicht unter «Duplikate»."""
    tenant = make_tenant(db)
    sharp = _circle_png_bytes(100, 75, 50)
    _upload(
        db,
        tenant.id,
        [("sharp.png", sharp), ("blurred.png", _blurred(sharp, radius=6)), ("different.png", _circle_png_bytes(40, 110, 45))],
    )
    service._refresh_tenant_similarity(db, tenant.id)

    assert service.list_similarity_groups(db, tenant.id, kind="duplicate").groups == []
    result = service.list_similarity_groups(db, tenant.id, kind="series")
    # Einzelbilder ohne Gegenstück erscheinen in keinem Tab.
    assert len(result.groups) == 1
    burst_group = result.groups[0]
    assert [image.original_name for image in burst_group.images] == ["sharp.png", "blurred.png"]
    assert burst_group.best_id == burst_group.images[0].id


def test_reencoded_copy_is_a_duplicate(db):
    tenant = make_tenant(db)
    sharp = _circle_png_bytes(100, 75, 50)
    _upload(db, tenant.id, [("original.png", sharp), ("copy.jpg", _reencoded(sharp))])
    service._refresh_tenant_similarity(db, tenant.id)

    assert _names(service.list_similarity_groups(db, tenant.id, kind="duplicate")) == [["copy.jpg", "original.png"]]
    assert service.list_similarity_groups(db, tenant.id, kind="series").groups == []


def test_grouping_scopes_to_the_given_tenant_only(db):
    tenant_a = make_tenant(db)
    tenant_b = make_tenant(db)
    content = _circle_png_bytes(100, 75, 50)
    _upload(db, tenant_a.id, [("a.png", content), ("a-blurred.png", _reencoded(content))])
    _upload(db, tenant_b.id, [("b.png", content), ("b-blurred.png", _reencoded(content))])

    service._refresh_tenant_similarity(db, tenant_a.id)

    assert _names(service.list_similarity_groups(db, tenant_a.id, kind="duplicate")) == [["a-blurred.png", "a.png"]]
    assert service.list_similarity_groups(db, tenant_b.id, kind="duplicate").status == "pending"
    stored = db.scalars(select(PhotoSimilarityResult).where(PhotoSimilarityResult.tenant_id == tenant_a.id)).all()
    assert {result.kind for result in stored} == {"duplicate", "series"}


def test_kind_series_groups_more_loosely_than_kind_duplicate(db):
    """"Duplikate" (kind="duplicate") only clusters near-identical re-encodes; "Ähnliche"
    (kind="series") uses the looser SERIES_HAMMING_THRESHOLD so a shifted frame of the same
    scene - not just a re-encode - still lands in the same series. The two shapes below have
    a real perceptual-hash distance of 10 (measured against SIMILARITY_HAMMING_THRESHOLD=5 /
    SERIES_HAMMING_THRESHOLD=14): too far apart for "duplicate", close enough for "series".
    `far` (distance 36 from `base`) stays separate under both - the looser threshold must not
    turn into "group everything"."""
    tenant = make_tenant(db)
    _upload(
        db,
        tenant.id,
        [
            ("base.png", _circle_png_bytes(100, 75, 50)),
            ("shifted.png", _circle_png_bytes(120, 75, 50)),
            ("far.png", _circle_png_bytes(40, 110, 45)),
        ],
    )
    service._refresh_tenant_similarity(db, tenant.id)

    assert service.list_similarity_groups(db, tenant.id, kind="duplicate").groups == []
    assert _names(service.list_similarity_groups(db, tenant.id, kind="series")) == [["base.png", "shifted.png"]]


def test_deleted_photos_drop_out_immediately_without_waiting_for_the_job(db):
    tenant = make_tenant(db)
    sharp = _circle_png_bytes(100, 75, 50)
    items = _upload(db, tenant.id, [("sharp.png", sharp), ("blurred.png", _reencoded(sharp))])
    service._refresh_tenant_similarity(db, tenant.id)
    blurred = next(item for item in items if item.original_name == "blurred.png")

    deleted, errors = service.delete_gallery_images(db, tenant.id, [blurred.id])
    db.commit()
    assert deleted == [blurred.id] and errors == []

    # Die Gruppe hat nur noch ein Bild - sie verschwindet, bevor der Job neu rechnet.
    assert service.list_similarity_groups(db, tenant.id, kind="duplicate").groups == []


def test_filters_narrow_the_stored_groups(db):
    tenant = make_tenant(db)
    sharp = _circle_png_bytes(100, 75, 50)
    _upload(db, tenant.id, [("sommerlager.png", sharp), ("sommerlager-2.png", _reencoded(sharp))])
    service._refresh_tenant_similarity(db, tenant.id)

    assert len(service.list_similarity_groups(db, tenant.id, kind="duplicate", search="sommerlager").groups) == 1
    assert service.list_similarity_groups(db, tenant.id, kind="duplicate", search="herbst").groups == []


def test_unchanged_photos_are_not_regrouped_and_changes_trigger_a_new_run(db, monkeypatch):
    """Der Job rechnet nur, wenn sich die Bildmenge geändert hat (Fingerabdruck) - sonst
    würde er bei jedem Tick alle Originale erneut lesen."""
    from app.services import file_service as module

    tenant = make_tenant(db)
    sharp = _circle_png_bytes(100, 75, 50)
    _upload(db, tenant.id, [("sharp.png", sharp), ("copy.png", _reencoded(sharp))])
    service._refresh_tenant_similarity(db, tenant.id)
    computed = []
    original_compute = FileService._compute_similarity_groups
    monkeypatch.setattr(
        FileService,
        "_compute_similarity_groups",
        lambda self, *args: computed.append(1) or original_compute(self, *args),
    )
    module._similarity_signatures.clear()

    service._refresh_tenant_similarity(db, tenant.id)
    assert computed == []

    _upload(db, tenant.id, [("other.png", _circle_png_bytes(40, 110, 45))])
    service._refresh_tenant_similarity(db, tenant.id)
    assert computed == [1]
    stored = db.get(PhotoSimilarityResult, (tenant.id, "duplicate"))
    assert stored.image_count == 3


def test_too_many_photos_are_reported_instead_of_grouped(db, monkeypatch):
    from app.services import file_service as module

    tenant = make_tenant(db)
    sharp = _circle_png_bytes(100, 75, 50)
    _upload(db, tenant.id, [("sharp.png", sharp), ("copy.png", _reencoded(sharp))])
    monkeypatch.setattr(module, "MAX_BACKGROUND_GROUPING_IMAGES", 1)

    service._refresh_tenant_similarity(db, tenant.id)

    result = service.list_similarity_groups(db, tenant.id, kind="series")
    assert result.status == "too_many"
    assert result.groups == []


def test_route_returns_the_stored_groups_for_writers_only(db):
    from fastapi import HTTPException

    tenant = make_tenant(db)
    sharp = _circle_png_bytes(100, 75, 50)
    _upload(db, tenant.id, [("sharp.png", sharp), ("blurred.png", _reencoded(sharp))])
    service._refresh_tenant_similarity(db, tenant.id)

    result = files_routes.list_similarity_groups(
        source=None, album_id=None, search=None, tags=None, kind="duplicate", db=db, user=make_current_user(tenant.id)
    )
    assert result.status == "ready"
    assert len(result.groups) == 1

    other = make_tenant(db)
    foreign = files_routes.list_similarity_groups(
        source=None, album_id=None, search=None, tags=None, kind="duplicate", db=db, user=make_current_user(other.id)
    )
    assert foreign.status == "pending" and foreign.groups == []

    with pytest.raises(HTTPException) as exc:
        files_routes.list_similarity_groups(
            source=None, album_id=None, search=None, tags=None, kind="duplicate", db=db, user=make_current_user(tenant.id, role="reader")
        )
    assert exc.value.status_code == 403
