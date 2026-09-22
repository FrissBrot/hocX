"""Tests for photo_event_link_service: date-based bidirectional linking between gallery
photos and Termine (see the module docstring for the two directions)."""
from datetime import UTC, date, datetime

from app.models.entities import GalleryImage, StoredFile
from app.services import photo_event_link_service as svc
from tests.factories import make_event, make_tenant


def _make_gallery_photo(db, tenant_id, *, exif_taken_at=None, event_id=None, event_auto_linked=False):
    stored_file = StoredFile(
        tenant_id=tenant_id, original_name="foto.png", mime_type="image/png",
        storage_path="uploads/tenant-x/gallery/foto.png", scan_status="clean",
        exif_taken_at=exif_taken_at,
    )
    db.add(stored_file)
    db.flush()
    gallery_image = GalleryImage(
        tenant_id=tenant_id, stored_file_id=stored_file.id, event_id=event_id, event_auto_linked=event_auto_linked,
    )
    db.add(gallery_image)
    db.flush()
    return stored_file, gallery_image


def test_find_matching_event_matches_single_day_event(db):
    tenant = make_tenant(db)
    event = make_event(db, tenant.id, title="Vorstandssitzung", event_date=date(2026, 7, 10))

    assert svc.find_matching_event(db, tenant.id, date(2026, 7, 10)) is not None
    assert svc.find_matching_event(db, tenant.id, date(2026, 7, 10)).id == event.id
    assert svc.find_matching_event(db, tenant.id, date(2026, 7, 11)) is None


def test_find_matching_event_matches_every_day_of_a_multi_day_event(db):
    tenant = make_tenant(db)
    event = make_event(db, tenant.id, title="Sommerlager", event_date=date(2026, 7, 10), event_end_date=date(2026, 7, 13))

    for day in (10, 11, 12, 13):
        match = svc.find_matching_event(db, tenant.id, date(2026, 7, day))
        assert match is not None and match.id == event.id
    assert svc.find_matching_event(db, tenant.id, date(2026, 7, 14)) is None
    assert svc.find_matching_event(db, tenant.id, date(2026, 7, 9)) is None


def test_find_matching_event_ignores_cancelled_events(db):
    tenant = make_tenant(db)
    make_event(db, tenant.id, title="Abgesagt", event_date=date(2026, 7, 10), is_cancelled=True)

    assert svc.find_matching_event(db, tenant.id, date(2026, 7, 10)) is None


def test_sync_photos_for_event_links_unlinked_photos_in_range(db):
    tenant = make_tenant(db)
    stored_file, gallery_image = _make_gallery_photo(db, tenant.id, exif_taken_at=datetime(2026, 7, 11, 9, 0, tzinfo=UTC))
    other_stored_file, other_gallery_image = _make_gallery_photo(db, tenant.id, exif_taken_at=datetime(2026, 9, 1, 9, 0, tzinfo=UTC))

    event = make_event(db, tenant.id, title="Sommerlager", event_date=date(2026, 7, 10), event_end_date=date(2026, 7, 13))
    svc.sync_photos_for_event(db, event)

    db.refresh(gallery_image)
    db.refresh(other_gallery_image)
    assert gallery_image.event_id == event.id
    assert gallery_image.event_auto_linked is True
    assert other_gallery_image.event_id is None


def test_sync_photos_for_event_does_not_override_a_manual_link(db):
    tenant = make_tenant(db)
    manual_event = make_event(db, tenant.id, title="Manuell gewaehlt", event_date=date(2026, 1, 1))
    _stored_file, gallery_image = _make_gallery_photo(
        db, tenant.id, exif_taken_at=datetime(2026, 7, 11, 9, 0, tzinfo=UTC),
        event_id=manual_event.id, event_auto_linked=False,
    )

    event = make_event(db, tenant.id, title="Sommerlager", event_date=date(2026, 7, 10), event_end_date=date(2026, 7, 13))
    svc.sync_photos_for_event(db, event)

    db.refresh(gallery_image)
    assert gallery_image.event_id == manual_event.id


def test_sync_photos_for_event_unlinks_auto_linked_photos_pushed_out_of_a_shrunk_range(db):
    tenant = make_tenant(db)
    event = make_event(db, tenant.id, title="Sommerlager", event_date=date(2026, 7, 10), event_end_date=date(2026, 7, 13))
    _stored_file, gallery_image = _make_gallery_photo(
        db, tenant.id, exif_taken_at=datetime(2026, 7, 13, 9, 0, tzinfo=UTC),
        event_id=event.id, event_auto_linked=True,
    )

    event.event_end_date = date(2026, 7, 11)
    db.commit()
    svc.sync_photos_for_event(db, event)

    db.refresh(gallery_image)
    assert gallery_image.event_id is None
    assert gallery_image.event_auto_linked is False
