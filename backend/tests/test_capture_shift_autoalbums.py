"""Datumskorrektur 1.5.1: Verschieben bei Fotos ohne Uhrzeit (nur der Tagesanteil wirkt) und
Nachziehen datumsabhängiger Auto-Alben (photo_album_item.auto_source, Migration 0218)."""

import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import select, text

from app.api.routes import files as files_routes
from app.models.entities import EventCycle, GalleryImage, PhotoAlbum, PhotoAlbumItem, StoredFile
from app.schemas.files import CaptureCorrectionUpdate, FileBulkCaptureDate, PhotoAlbumItemsUpdate
from app.services import image_metadata_service, photo_album_service
from app.services.capture_date import effective_capture
from app.services.file_service import FileService
from tests.factories import make_app_user, make_current_user, make_cycle_config, make_event, make_tenant

service = FileService()


def _user(db, tenant):
    app_user = make_app_user(db, email=f"{uuid.uuid4().hex[:10]}@example.com", tenant_id=tenant.id, role_code="writer")
    return make_current_user(tenant.id, role="writer", user_id=app_user.id)


def _photo(db, tenant_id, *, exif=None, estimated=None):
    stored_file = StoredFile(
        tenant_id=tenant_id,
        original_name="foto.jpg",
        mime_type="image/jpeg",
        storage_path=f"uploads/{uuid.uuid4().hex}-foto.jpg",
        exif_taken_at=exif,
        estimated_taken_on=estimated,
        metadata_scanned_at=datetime.now(UTC),
    )
    db.add(stored_file)
    db.flush()
    db.add(GalleryImage(tenant_id=tenant_id, stored_file_id=stored_file.id))
    db.flush()
    return stored_file


def _shift(db, user, photos, *, days=0, hours=0):
    return files_routes.bulk_update_capture_date(
        FileBulkCaptureDate(file_ids=[photo.public_id for photo in photos], mode="shift", shift_days=days, shift_hours=hours), db, user
    )


# --- Verschieben ohne Uhrzeit: nur Tage wirken ------------------------------------------------


def test_shifted_correction_without_time_uses_only_whole_days():
    estimated = SimpleNamespace(capture_corrected_at=None, capture_corrected_has_time=False, exif_taken_at=None, estimated_taken_on=date(2024, 3, 10))
    day = lambda delta: image_metadata_service.shifted_correction(estimated, delta)[0].date()  # noqa: E731
    assert day(timedelta(hours=-13)) == date(2024, 3, 10)  # früher: Vortag (12:00 - 13 h)
    assert day(timedelta(hours=13)) == date(2024, 3, 10)
    assert day(timedelta(hours=-30)) == date(2024, 3, 9)
    assert day(timedelta(days=1, hours=-2)) == date(2024, 3, 10)  # gesamt +22 h, kein ganzer Tag
    assert day(timedelta(days=-2, hours=-5)) == date(2024, 3, 8)
    assert image_metadata_service.shifted_correction(estimated, timedelta(hours=5))[1] is False

    with_time = SimpleNamespace(
        capture_corrected_at=None, capture_corrected_has_time=False, exif_taken_at=datetime(2024, 3, 10, 8, 0, tzinfo=UTC), estimated_taken_on=None
    )
    assert image_metadata_service.shifted_correction(with_time, timedelta(hours=-13)) == (datetime(2024, 3, 9, 19, 0), True)


def test_bulk_shift_hours_leave_photos_without_time_unchanged(db):
    tenant = make_tenant(db)
    user = _user(db, tenant)
    estimated = _photo(db, tenant.id, estimated=date(2024, 3, 10))
    with_time = _photo(db, tenant.id, exif=datetime(2024, 3, 10, 8, 0, tzinfo=UTC))

    result = _shift(db, user, [estimated, with_time], hours=-13)

    assert result.updated_ids == [with_time.public_id]
    assert result.no_time_unchanged_ids == [estimated.public_id]
    assert result.date_only_ids == [] and result.unchanged_ids == []
    db.refresh(estimated)
    db.refresh(with_time)
    # Keine Korrektur angelegt, nichts für den Datei-Sync vorgemerkt
    assert estimated.capture_corrected_at is None and estimated.capture_file_state is None
    assert effective_capture(estimated) == (date(2024, 3, 10), "estimated")
    # Mit Uhrzeit wie bisher: über Mitternacht auf den Vortag
    assert with_time.capture_corrected_at.replace(tzinfo=None) == datetime(2024, 3, 9, 19, 0)
    assert with_time.capture_file_state == "pending"

    result = _shift(db, user, [estimated], hours=13)
    assert result.no_time_unchanged_ids == [estimated.public_id] and result.updated_ids == []


def test_bulk_shift_days_apply_to_photos_without_time_and_hours_are_reported(db):
    tenant = make_tenant(db)
    user = _user(db, tenant)
    estimated = _photo(db, tenant.id, estimated=date(2024, 3, 10))
    with_time = _photo(db, tenant.id, exif=datetime(2024, 3, 10, 8, 0, tzinfo=UTC))

    result = _shift(db, user, [estimated, with_time], days=2)
    assert result.updated_ids == [estimated.public_id, with_time.public_id]
    assert result.date_only_ids == []  # ganze Tage: nichts ignoriert
    db.refresh(estimated)
    assert effective_capture(estimated) == (date(2024, 3, 12), "corrected")
    assert estimated.capture_corrected_has_time is False and estimated.capture_file_state == "pending"

    result = _shift(db, user, [estimated, with_time], days=-1, hours=-5)
    assert result.updated_ids == [estimated.public_id, with_time.public_id]
    assert result.date_only_ids == [estimated.public_id]
    db.refresh(estimated)
    db.refresh(with_time)
    assert effective_capture(estimated) == (date(2024, 3, 11), "corrected")
    assert with_time.capture_corrected_at.replace(tzinfo=None) == datetime(2024, 3, 11, 3, 0)

    audit_details = db.execute(
        text("SELECT details_json FROM audit_log WHERE tenant_id = :t AND action = 'photo.capture_date_shifted' ORDER BY id DESC LIMIT 1"),
        {"t": tenant.id},
    ).scalar_one()
    assert audit_details["date_only"] == 1 and audit_details["no_time_unchanged"] == 0


# --- Auto-Alben nachziehen ----------------------------------------------------------------------


def _cycle_upload(db, tenant_id, cycle_config, photo, on_date):
    """Wie ein Galerie-Upload mit Ziel «Zyklus»: Periode aus dem Aufnahmedatum."""
    photo_album_service.assign_uploaded_files(
        db, service, tenant_id=tenant_id, stored_file_public_ids=[photo.public_id], cycle_config=cycle_config, fallback_date=on_date
    )


def _album(db, tenant_id, cycle_config, year):
    return db.scalar(
        select(PhotoAlbum).where(
            PhotoAlbum.tenant_id == tenant_id, PhotoAlbum.kind == "cycle", PhotoAlbum.cycle_config_id == cycle_config.id, PhotoAlbum.cycle_year == year
        )
    )


def _items(db, photo):
    return {
        (row.album_id, row.auto_source)
        for row in db.scalars(select(PhotoAlbumItem).where(PhotoAlbumItem.file_id == photo.public_id))
    }


def test_correction_moves_photo_to_the_new_cycle_period_and_termin(db):
    tenant = make_tenant(db)
    user = _user(db, tenant)
    biber = make_cycle_config(db, tenant.id, name="Biber", reset_month=7, reset_day=31)
    old_event = make_event(db, tenant.id, title="Falsche Kamerazeit", event_date=date(2001, 5, 1))
    new_event = make_event(db, tenant.id, title="Herbstlager", event_date=date(2024, 9, 1))
    photo = _photo(db, tenant.id, exif=datetime(2001, 5, 1, 10, 0, tzinfo=UTC))  # Kamera-Jahr falsch
    gallery_image = db.scalar(select(GalleryImage).where(GalleryImage.stored_file_id == photo.id))
    gallery_image.event_id, gallery_image.event_auto_linked = old_event.id, True
    db.flush()
    _cycle_upload(db, tenant.id, biber, photo, date(2001, 5, 1))
    old_album = _album(db, tenant.id, biber, 2000)
    assert _items(db, photo) == {(old_album.id, "capture_date")}

    files_routes.update_stored_file_capture_correction(photo.public_id, CaptureCorrectionUpdate(corrected_date=date(2024, 9, 1)), db, user)

    new_album = _album(db, tenant.id, biber, 2024)
    assert new_album is not None
    assert _items(db, photo) == {(new_album.id, "capture_date")}  # raus aus 2000, rein in 2024
    db.refresh(gallery_image)
    assert gallery_image.event_id == new_event.id and gallery_image.event_auto_linked is True

    # Zurücksetzen: wieder EXIF 2001 -> zurück in die alte Periode und zum alten Termin
    files_routes.bulk_update_capture_date(FileBulkCaptureDate(file_ids=[photo.public_id], mode="reset"), db, user)
    assert _items(db, photo) == {(old_album.id, "capture_date")}
    db.refresh(gallery_image)
    assert gallery_image.event_id == old_event.id

    # Verschieben ohne Periodenwechsel: nichts zu tun
    _shift(db, user, [photo], days=1)
    assert _items(db, photo) == {(old_album.id, "capture_date")}


def test_estimated_date_edit_moves_cycle_period_too(db):
    tenant = make_tenant(db)
    wolf = make_cycle_config(db, tenant.id, name="Wolf")  # Kalenderjahr
    photo = _photo(db, tenant.id, estimated=date(2019, 6, 1))
    _cycle_upload(db, tenant.id, wolf, photo, date(2019, 6, 1))

    service.update_estimated_capture_date(db, photo, date(2023, 6, 1), user_id=None)

    assert _items(db, photo) == {(_album(db, tenant.id, wolf, 2023).id, "capture_date")}


def test_manual_album_assignments_are_never_moved(db):
    tenant = make_tenant(db)
    user = _user(db, tenant)
    biber = make_cycle_config(db, tenant.id, name="Biber", reset_month=7, reset_day=31)
    event = make_event(db, tenant.id, title="Pfila", event_date=date(2001, 5, 1))
    db.add(EventCycle(event_id=event.id, cycle_config_id=biber.id, cycle_year=2000))
    manual_album = PhotoAlbum(tenant_id=tenant.id, name="Eigenes Album", kind="manual")
    db.add(manual_album)
    db.flush()

    # a) von Hand in das Zyklus-Album gelegt, b) Upload auf einen bewusst gewählten Termin
    #    (dessen Zyklus-Album), c) Auto-Eintrag, danach von Hand bestätigt (wird manuell)
    by_hand = _photo(db, tenant.id, exif=datetime(2001, 5, 1, tzinfo=UTC))
    via_event = _photo(db, tenant.id, exif=datetime(2001, 5, 1, tzinfo=UTC))
    confirmed = _photo(db, tenant.id, exif=datetime(2001, 5, 1, tzinfo=UTC))
    old_album = photo_album_service.get_or_create_cycle_album(db, tenant_id=tenant.id, cycle_config=biber, cycle_year=2000)
    db.commit()
    files_routes.add_album_items(old_album.id, PhotoAlbumItemsUpdate(file_ids=[by_hand.public_id]), db, user)
    files_routes.add_album_items(manual_album.id, PhotoAlbumItemsUpdate(file_ids=[by_hand.public_id]), db, user)
    photo_album_service.assign_uploaded_files(db, service, tenant_id=tenant.id, stored_file_public_ids=[via_event.public_id], event_id=event.id)
    _cycle_upload(db, tenant.id, biber, confirmed, date(2001, 5, 1))
    files_routes.add_album_items(old_album.id, PhotoAlbumItemsUpdate(file_ids=[confirmed.public_id]), db, user)
    before = {photo.public_id: _items(db, photo) for photo in (by_hand, via_event, confirmed)}
    assert before[by_hand.public_id] == {(old_album.id, None), (manual_album.id, None)}
    assert before[via_event.public_id] == {(old_album.id, None)}
    assert before[confirmed.public_id] == {(old_album.id, None)}

    files_routes.bulk_update_capture_date(
        FileBulkCaptureDate(file_ids=list(before), mode="set", corrected_date=date(2024, 9, 1)), db, user
    )

    assert {photo.public_id: _items(db, photo) for photo in (by_hand, via_event, confirmed)} == before
    assert _album(db, tenant.id, biber, 2024) is None  # kein Album angelegt


def test_auto_entry_does_not_duplicate_an_existing_manual_entry_in_the_target(db):
    tenant = make_tenant(db)
    user = _user(db, tenant)
    wolf = make_cycle_config(db, tenant.id, name="Wolf")
    photo = _photo(db, tenant.id, exif=datetime(2019, 6, 1, tzinfo=UTC))
    _cycle_upload(db, tenant.id, wolf, photo, date(2019, 6, 1))
    target = photo_album_service.get_or_create_cycle_album(db, tenant_id=tenant.id, cycle_config=wolf, cycle_year=2023)
    db.commit()
    files_routes.add_album_items(target.id, PhotoAlbumItemsUpdate(file_ids=[photo.public_id]), db, user)

    files_routes.bulk_update_capture_date(FileBulkCaptureDate(file_ids=[photo.public_id], mode="set", corrected_date=date(2023, 6, 1)), db, user)

    assert _items(db, photo) == {(target.id, None)}  # alter Auto-Eintrag weg, manueller bleibt manuell


def test_foreign_tenant_albums_are_untouched(db):
    tenant = make_tenant(db)
    other = make_tenant(db)
    user = _user(db, tenant)
    other_cycle = make_cycle_config(db, other.id, name="Fremd")
    foreign = _photo(db, other.id, exif=datetime(2019, 6, 1, tzinfo=UTC))
    _cycle_upload(db, other.id, other_cycle, foreign, date(2019, 6, 1))
    before = _items(db, foreign)

    result = files_routes.bulk_update_capture_date(
        FileBulkCaptureDate(file_ids=[foreign.public_id], mode="set", corrected_date=date(2023, 6, 1)), db, user
    )
    assert result.not_found_ids == [foreign.public_id]
    # Auch direkt mit fremdem Mandanten aufgerufen: nichts
    assert photo_album_service.follow_capture_date_change(db, tenant_id=tenant.id, stored_files=[foreign]) == set()
    assert _items(db, foreign) == before
    db.refresh(foreign)
    assert foreign.capture_corrected_at is None
