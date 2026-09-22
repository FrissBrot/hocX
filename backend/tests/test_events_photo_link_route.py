"""Route-level wiring check: POST /events and PATCH /events/{id} must call
photo_event_link_service.sync_photos_for_event so an already-uploaded gallery photo gets
linked/unlinked as Termine are created or their dates edited - the actual matching logic
itself is covered in isolation by tests/test_photo_event_link_service.py."""
from datetime import UTC, date, datetime

from app.api.routes import events as events_routes
from app.models.entities import GalleryImage, StoredFile
from app.schemas.event import EventCreate, EventUpdate
from tests.factories import make_current_user, make_event, make_tenant


def _make_gallery_photo(db, tenant_id, *, exif_taken_at):
    stored_file = StoredFile(
        tenant_id=tenant_id, original_name="foto.png", mime_type="image/png",
        storage_path="uploads/tenant-x/gallery/foto.png", scan_status="clean",
        exif_taken_at=exif_taken_at,
    )
    db.add(stored_file)
    db.flush()
    gallery_image = GalleryImage(tenant_id=tenant_id, stored_file_id=stored_file.id)
    db.add(gallery_image)
    db.flush()
    return gallery_image


def test_create_event_route_auto_links_existing_photos_on_matching_dates(db):
    tenant = make_tenant(db)
    writer = make_current_user(tenant.id, role="writer")
    gallery_image = _make_gallery_photo(db, tenant.id, exif_taken_at=datetime(2026, 7, 11, 10, 0, tzinfo=UTC))

    events_routes.create_event(
        EventCreate(event_date=date(2026, 7, 10), event_end_date=date(2026, 7, 13), title="Sommerlager"),
        db=db, user=writer,
    )

    db.refresh(gallery_image)
    assert gallery_image.event_id is not None
    assert gallery_image.event_auto_linked is True


def test_patch_event_route_unlinks_photos_pushed_out_by_a_shrunk_range(db):
    tenant = make_tenant(db)
    writer = make_current_user(tenant.id, role="writer")
    event = make_event(db, tenant.id, title="Sommerlager", event_date=date(2026, 7, 10), event_end_date=date(2026, 7, 13))
    gallery_image = _make_gallery_photo(db, tenant.id, exif_taken_at=datetime(2026, 7, 13, 10, 0, tzinfo=UTC))
    gallery_image.event_id = event.id
    gallery_image.event_auto_linked = True
    db.commit()

    events_routes.patch_event(event.public_id, EventUpdate(event_end_date=date(2026, 7, 11)), db=db, user=writer)

    db.refresh(gallery_image)
    assert gallery_image.event_id is None
    assert gallery_image.event_auto_linked is False
