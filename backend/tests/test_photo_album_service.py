"""Tests for photo_album_service.py: auto-album resolution (one per Zyklus+Periode, one per
Abgabe, one per Abgabe-Element) and the best-of ("Stern") ranking within an album."""

import asyncio
import io
import random
from datetime import date

import pytest
from PIL import Image
from sqlalchemy import text

from app.core.config import settings
from app.core.cycle_utils import format_cycle_name
from app.models.entities import EventCycle, PhotoAlbum, PhotoAlbumItem
from app.services import photo_album_service
from app.services.file_service import FileService
from tests.factories import make_cycle_config, make_event, make_tenant

service = FileService()


def _noise_png_bytes(seed: int) -> bytes:
    # Random per-pixel noise, not a solid fill - a batch of same-color images all phash
    # near-identically and trip the perceptual-duplicate-warning path save_gallery_uploads
    # already has (see _closest_perceptual_match), which isn't what these tests are about.
    rng = random.Random(seed)
    data = bytes(rng.randrange(256) for _ in range(48 * 48 * 3))
    buffer = io.BytesIO()
    Image.frombytes("RGB", (48, 48), data).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture(autouse=True)
def _isolated_storage_root(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(settings, "upload_root", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "thumbnail_root", str(tmp_path / "thumbnails"))


def _upload_images(db, tenant_id: int, count: int) -> list:
    """Real gallery uploads (so scores/thumbnails/scan pipeline all run for real), forced
    past the pending-AV-scan gate the way test_photo_analysis_auto_queue.py does - there's
    no ClamAV in this test environment."""
    files = [(f"bild-{i}.png", _noise_png_bytes(i)) for i in range(count)]
    items, errors = asyncio.run(service.save_gallery_uploads(db, tenant_id=tenant_id, files=files, tags=[], created_by=None))
    assert errors == []
    db.execute(text("UPDATE stored_file SET scan_status = 'clean' WHERE tenant_id = :tenant_id"), {"tenant_id": tenant_id})
    db.commit()
    return items


def _set_scores(db, file_id, *, sharpness=None, exposure=None, face_quality=None) -> None:
    db.execute(
        text(
            "UPDATE stored_file SET sharpness_score = :s, exposure_score = :e, face_quality_score = :f "
            "WHERE public_id = :id"
        ),
        {"s": sharpness, "e": exposure, "f": face_quality, "id": file_id},
    )
    db.commit()


def test_get_or_create_cycle_album_is_idempotent_and_named_from_pattern(db):
    tenant = make_tenant(db)
    cycle_config = make_cycle_config(db, tenant.id, name="Biber", reset_month=7, reset_day=31)
    cycle_config.name_pattern = "Biber [cy]/[cy_end]"
    db.commit()

    first = photo_album_service.get_or_create_cycle_album(db, tenant_id=tenant.id, cycle_config=cycle_config, cycle_year=2026)
    second = photo_album_service.get_or_create_cycle_album(db, tenant_id=tenant.id, cycle_config=cycle_config, cycle_year=2026)

    assert first.id == second.id
    assert first.kind == "cycle"
    assert first.name == format_cycle_name(cycle_config.name_pattern, 2026) == "Biber 2026/2027"

    other_year = photo_album_service.get_or_create_cycle_album(db, tenant_id=tenant.id, cycle_config=cycle_config, cycle_year=2025)
    assert other_year.id != first.id


def test_cycle_albums_for_event_resolves_via_event_cycle(db):
    tenant = make_tenant(db)
    cycle_config = make_cycle_config(db, tenant.id, name="Wolf")
    event = make_event(db, tenant.id, title="Sommerlager", event_date=date(2026, 7, 1))
    db.add(EventCycle(event_id=event.id, cycle_config_id=cycle_config.id, cycle_year=2026))
    db.commit()

    albums = photo_album_service.cycle_albums_for_event(db, tenant_id=tenant.id, event_id=event.id)

    assert len(albums) == 1
    assert albums[0].kind == "cycle"
    assert albums[0].cycle_config_id == cycle_config.id
    assert albums[0].cycle_year == 2026


def test_recompute_best_of_stars_the_top_scoring_fraction(db):
    """10 images, BEST_OF_FRACTION=0.15 -> round(10*0.15)=2 slots. Scores are spread out
    (10, 20, ..., 100) so the top 2 (90, 100) should end up starred and nothing else."""
    tenant = make_tenant(db)
    items = _upload_images(db, tenant.id, 10)
    album = PhotoAlbum(tenant_id=tenant.id, name="Test", kind="manual")
    db.add(album)
    db.flush()
    photo_album_service.add_items(db, album, [item.id for item in items])
    db.commit()

    for index, item in enumerate(items):
        _set_scores(db, item.id, sharpness=(index + 1) * 100, exposure=1.0)

    photo_album_service.recompute_best_of(db, service, album)

    rows = {row.file_id: row.is_best for row in db.query(PhotoAlbumItem).filter_by(album_id=album.id)}
    starred = {item.id for item in items if rows[item.id]}
    top_two = {items[-1].id, items[-2].id}
    assert starred == top_two


def test_recompute_best_of_respects_manual_override(db):
    tenant = make_tenant(db)
    items = _upload_images(db, tenant.id, 10)
    album = PhotoAlbum(tenant_id=tenant.id, name="Test", kind="manual")
    db.add(album)
    db.flush()
    photo_album_service.add_items(db, album, [item.id for item in items])
    db.commit()

    for index, item in enumerate(items):
        _set_scores(db, item.id, sharpness=(index + 1) * 100, exposure=1.0)

    # Pin the worst-scoring photo in, and the best-scoring photo out.
    worst, best = items[0], items[-1]
    photo_album_service.set_best_override(db, service, album, worst.id, "include")
    photo_album_service.set_best_override(db, service, album, best.id, "exclude")

    rows = {row.file_id: row.is_best for row in db.query(PhotoAlbumItem).filter_by(album_id=album.id)}
    assert rows[worst.id] is True
    assert rows[best.id] is False


def test_recompute_best_of_skips_photos_below_the_relative_score_floor(db):
    """One clear standout (sharpness 1000) and nine near-zero photos: the floor
    (BEST_OF_MIN_SCORE_RATIO of the best score) should keep the near-zero ones out of the
    best-of selection even though the fraction would allow more than one star."""
    tenant = make_tenant(db)
    items = _upload_images(db, tenant.id, 10)
    album = PhotoAlbum(tenant_id=tenant.id, name="Test", kind="manual")
    db.add(album)
    db.flush()
    photo_album_service.add_items(db, album, [item.id for item in items])
    db.commit()

    _set_scores(db, items[0].id, sharpness=1000, exposure=1.0)
    for item in items[1:]:
        _set_scores(db, item.id, sharpness=1, exposure=1.0)

    photo_album_service.recompute_best_of(db, service, album)

    rows = {row.file_id: row.is_best for row in db.query(PhotoAlbumItem).filter_by(album_id=album.id)}
    assert rows[items[0].id] is True
    assert all(rows[item.id] is False for item in items[1:])


def test_recompute_best_of_excludes_severely_underexposed_photos(db):
    """4 photos -> round(4*0.15) = 1 slot. Two low-scoring fillers keep the floor low
    enough that the exposure gate is the only thing deciding between the two candidates,
    which otherwise share the same sharpness."""
    tenant = make_tenant(db)
    items = _upload_images(db, tenant.id, 4)
    album = PhotoAlbum(tenant_id=tenant.id, name="Test", kind="manual")
    db.add(album)
    db.flush()
    photo_album_service.add_items(db, album, [item.id for item in items])
    db.commit()

    _set_scores(db, items[0].id, sharpness=5, exposure=1.0)
    _set_scores(db, items[1].id, sharpness=5, exposure=1.0)
    # Same sharpness, but one candidate is badly underexposed (below BEST_OF_MIN_EXPOSURE).
    _set_scores(db, items[2].id, sharpness=500, exposure=0.05)
    _set_scores(db, items[3].id, sharpness=500, exposure=0.9)

    photo_album_service.recompute_best_of(db, service, album)

    rows = {row.file_id: row.is_best for row in db.query(PhotoAlbumItem).filter_by(album_id=album.id)}
    assert rows[items[2].id] is False
    assert rows[items[3].id] is True


def test_list_albums_with_stats_reports_counts_and_up_to_four_covers(db):
    tenant = make_tenant(db)
    items = _upload_images(db, tenant.id, 6)
    album = PhotoAlbum(tenant_id=tenant.id, name="Test", kind="manual")
    db.add(album)
    db.flush()
    photo_album_service.add_items(db, album, [item.id for item in items])
    db.commit()
    for index, item in enumerate(items):
        _set_scores(db, item.id, sharpness=(index + 1) * 100, exposure=1.0)
    photo_album_service.recompute_best_of(db, service, album)

    entries = photo_album_service.list_albums_with_stats(db, service, tenant.id)

    entry = next(e for e in entries if e.album.id == album.id)
    assert entry.photo_count == 6
    # BEST_OF_FRACTION=0.15 of 6 -> round(0.9) = 1 slot starred.
    assert entry.best_of_count == 1
    assert len(entry.cover_thumbnail_urls) == 4
    assert len(set(entry.cover_thumbnail_urls)) == 4


def test_list_albums_with_stats_reports_zero_for_an_empty_album(db):
    tenant = make_tenant(db)
    album = PhotoAlbum(tenant_id=tenant.id, name="Leer", kind="manual")
    db.add(album)
    db.commit()

    entries = photo_album_service.list_albums_with_stats(db, service, tenant.id)

    entry = next(e for e in entries if e.album.id == album.id)
    assert entry.photo_count == 0
    assert entry.best_of_count == 0
    assert entry.cover_thumbnail_urls == []


def test_list_albums_with_stats_scopes_to_the_given_tenant_only(db):
    tenant_a = make_tenant(db)
    tenant_b = make_tenant(db)
    PhotoAlbum(tenant_id=tenant_a.id, name="A", kind="manual")
    album_b = PhotoAlbum(tenant_id=tenant_b.id, name="B", kind="manual")
    db.add(album_b)
    db.commit()

    entries = photo_album_service.list_albums_with_stats(db, service, tenant_a.id)

    assert all(e.album.tenant_id == tenant_a.id for e in entries)
    assert album_b.id not in {e.album.id for e in entries}


def test_drop_items_for_files_removes_rows_and_returns_touched_album_ids(db):
    tenant = make_tenant(db)
    items = _upload_images(db, tenant.id, 3)
    album = PhotoAlbum(tenant_id=tenant.id, name="Test", kind="manual")
    db.add(album)
    db.flush()
    photo_album_service.add_items(db, album, [item.id for item in items])
    db.commit()

    touched = photo_album_service.drop_items_for_files(db, [items[0].id])
    db.commit()

    assert touched == {album.id}
    remaining = {row.file_id for row in db.query(PhotoAlbumItem).filter_by(album_id=album.id)}
    assert items[0].id not in remaining
    assert {items[1].id, items[2].id} == remaining


def test_drop_items_for_files_with_no_matching_rows_returns_empty_set(db):
    tenant = make_tenant(db)
    items = _upload_images(db, tenant.id, 1)

    touched = photo_album_service.drop_items_for_files(db, [items[0].id])

    assert touched == set()


def test_set_best_override_everywhere_applies_to_every_album_the_photo_is_in(db):
    """Best-of toggle from the unscoped "Alle Fotos" view (no single album in context) -
    is_best lives on PhotoAlbumItem, so pinning it must reach every album containing the
    photo, not just one."""
    tenant = make_tenant(db)
    items = _upload_images(db, tenant.id, 3)
    photo = items[0]
    album_1 = PhotoAlbum(tenant_id=tenant.id, name="Erstes", kind="manual")
    album_2 = PhotoAlbum(tenant_id=tenant.id, name="Zweites", kind="manual")
    db.add_all([album_1, album_2])
    db.flush()
    photo_album_service.add_items(db, album_1, [item.id for item in items])
    photo_album_service.add_items(db, album_2, [photo.id])
    db.commit()

    touched = photo_album_service.set_best_override_everywhere(db, service, tenant.id, photo.id, "include")

    assert touched == 2
    is_best_by_album = {
        row.album_id: row.is_best for row in db.query(PhotoAlbumItem).filter_by(file_id=photo.id)
    }
    assert is_best_by_album == {album_1.id: True, album_2.id: True}


def test_set_best_override_everywhere_returns_zero_when_photo_is_in_no_album(db):
    tenant = make_tenant(db)
    items = _upload_images(db, tenant.id, 1)

    touched = photo_album_service.set_best_override_everywhere(db, service, tenant.id, items[0].id, "include")

    assert touched == 0


def test_set_best_override_everywhere_is_scoped_to_the_given_tenant(db):
    tenant_a = make_tenant(db)
    tenant_b = make_tenant(db)
    items_a = _upload_images(db, tenant_a.id, 1)
    album_b = PhotoAlbum(tenant_id=tenant_b.id, name="B", kind="manual")
    db.add(album_b)
    db.commit()

    # A photo id that happens to exist (in another tenant's album) must not be reachable
    # through tenant_a's scope.
    touched = photo_album_service.set_best_override_everywhere(db, service, tenant_b.id, items_a[0].id, "include")

    assert touched == 0
