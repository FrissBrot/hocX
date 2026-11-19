"""Korrigiertes Aufnahmedatum (Migration 0200): Einzelbearbeitung im Foto-Viewer
(PATCH /stored-files/{id}/capture-correction) und Mehrfachauswahl der Galerie
(POST /files/bulk-capture-date) - Rechte, Mandantentrennung, Partner-Fotos, Obergrenze,
Versatz, Zurücksetzen, Vorrang in Sortierung/Filter und Termin-Verknüpfung, Export, Audit."""

import uuid
from datetime import UTC, date, datetime, time, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import text

from app.api.routes import files as files_routes
from app.models.entities import GalleryImage, PhotoAlbum, PhotoAlbumItem, StoredFile
from app.repositories.file_repository import StoredFileRepository
from app.schemas.files import (
    MAX_CAPTURE_DATE_BULK,
    AlbumShareCreate,
    AlbumShareRespond,
    CaptureCorrectionUpdate,
    FileBulkCaptureDate,
)
from app.services import image_export_service
from app.services.capture_date import auto_link_date, effective_capture, effective_capture_moment
from tests.factories import make_app_user, make_current_user, make_event, make_tenant
from tests.image_fixtures import jpeg, read_exif


def _user(db, tenant, role="writer", email=None):
    app_user = make_app_user(db, email=email or f"{uuid.uuid4().hex[:10]}@example.com", tenant_id=tenant.id, role_code=role)
    return make_current_user(tenant.id, role=role, user_id=app_user.id)


def _photo(db, tenant_id, *, name="foto.jpg", exif=None, estimated=None, created_at=None, mime="image/jpeg"):
    stored_file = StoredFile(
        tenant_id=tenant_id,
        original_name=name,
        mime_type=mime,
        storage_path=f"uploads/{uuid.uuid4().hex}-{name}",
        exif_taken_at=exif,
        estimated_taken_on=estimated,
        metadata_scanned_at=datetime.now(UTC),
    )
    if created_at is not None:
        stored_file.created_at = created_at
    db.add(stored_file)
    db.flush()
    db.add(GalleryImage(tenant_id=tenant_id, stored_file_id=stored_file.id))
    db.flush()
    return stored_file


def _audit_rows(db, tenant_id):
    return db.execute(
        text("SELECT action, entity_id, details_json FROM audit_log WHERE tenant_id = :t AND action LIKE 'photo.capture_date_%' ORDER BY id"),
        {"t": tenant_id},
    ).all()


# --- Einzelbearbeitung --------------------------------------------------------------------


def test_single_correction_takes_precedence_keeps_exif_and_can_be_reset(db):
    tenant = make_tenant(db)
    user = _user(db, tenant)
    exif = datetime(2019, 3, 4, 10, 30, tzinfo=UTC)
    photo = _photo(db, tenant.id, exif=exif)

    metadata = files_routes.update_stored_file_capture_correction(
        photo.public_id, CaptureCorrectionUpdate(corrected_date=date(2021, 6, 5), corrected_time=time(14, 15)), db, user
    )
    assert metadata.date_source == "corrected"
    assert metadata.effective_date == date(2021, 6, 5)
    assert metadata.capture_corrected_at.replace(tzinfo=None) == datetime(2021, 6, 5, 14, 15)
    assert metadata.capture_corrected_has_time is True
    assert metadata.exif_taken_at == exif  # Original bleibt erhalten («ursprünglich (EXIF)»)
    assert metadata.capture_corrected_set_by_name
    db.refresh(photo)
    assert photo.exif_taken_at == exif

    reset = files_routes.update_stored_file_capture_correction(photo.public_id, CaptureCorrectionUpdate(corrected_date=None), db, user)
    assert reset.date_source == "exif"
    assert reset.effective_date == date(2019, 3, 4)
    assert reset.capture_corrected_at is None
    db.refresh(photo)
    assert photo.capture_corrected_at is None and photo.capture_corrected_set_by is None

    actions = [row.action for row in _audit_rows(db, tenant.id)]
    assert actions == ["photo.capture_date_corrected", "photo.capture_date_reset"]


def test_single_correction_without_time_is_a_date(db):
    tenant = make_tenant(db)
    user = _user(db, tenant)
    photo = _photo(db, tenant.id)
    metadata = files_routes.update_stored_file_capture_correction(
        photo.public_id, CaptureCorrectionUpdate(corrected_date=date(1999, 12, 31)), db, user
    )
    assert metadata.capture_corrected_has_time is False
    assert metadata.effective_date == date(1999, 12, 31)


def test_single_correction_rejects_implausible_dates(db):
    tenant = make_tenant(db)
    user = _user(db, tenant)
    photo = _photo(db, tenant.id)
    for bad in (date(1700, 1, 1), date.today() + timedelta(days=30)):
        with pytest.raises(HTTPException) as exc_info:
            files_routes.update_stored_file_capture_correction(photo.public_id, CaptureCorrectionUpdate(corrected_date=bad), db, user)
        assert exc_info.value.status_code == 422
    db.refresh(photo)
    assert photo.capture_corrected_at is None


def test_single_correction_requires_photos_manage(db):
    tenant = make_tenant(db)
    reader = _user(db, tenant, role="reader")
    photo = _photo(db, tenant.id)
    with pytest.raises(HTTPException) as exc_info:
        files_routes.update_stored_file_capture_correction(photo.public_id, CaptureCorrectionUpdate(corrected_date=date(2020, 1, 1)), db, reader)
    assert exc_info.value.status_code == 403
    with pytest.raises(HTTPException) as exc_info:
        files_routes.bulk_update_capture_date(FileBulkCaptureDate(file_ids=[photo.public_id], mode="reset"), db, reader)
    assert exc_info.value.status_code == 403


# --- Mandantentrennung und Partner-Fotos -----------------------------------------------------


def test_foreign_tenant_photo_is_not_found_and_unchanged(db):
    own = make_tenant(db)
    other = make_tenant(db)
    user = _user(db, own)
    foreign = _photo(db, other.id, exif=datetime(2018, 1, 1, tzinfo=UTC))
    unknown = uuid.uuid4()

    statuses = []
    for target in (foreign.public_id, unknown):
        with pytest.raises(HTTPException) as exc_info:
            files_routes.update_stored_file_capture_correction(target, CaptureCorrectionUpdate(corrected_date=date(2020, 1, 1)), db, user)
        statuses.append((exc_info.value.status_code, exc_info.value.detail))
    # Fremd und unbekannt sind nicht unterscheidbar (kein Existenz-Orakel).
    assert statuses[0] == statuses[1] == (404, "Stored file not found")

    own_photo = _photo(db, own.id)
    result = files_routes.bulk_update_capture_date(
        FileBulkCaptureDate(file_ids=[own_photo.public_id, foreign.public_id, unknown], mode="set", corrected_date=date(2020, 1, 1)), db, user
    )
    assert result.updated_ids == [own_photo.public_id]
    assert result.not_found_ids == [foreign.public_id, unknown]
    db.refresh(foreign)
    assert foreign.capture_corrected_at is None
    # Audit nennt nur die eigenen, geänderten Bilder
    (row,) = _audit_rows(db, own.id)
    assert row.details_json["file_ids"] == [str(own_photo.public_id)]
    assert row.details_json["not_found"] == 2


def test_partner_photo_from_shared_album_cannot_be_corrected(db):
    owner = make_tenant(db)
    partner = make_tenant(db)
    owner_user = _user(db, owner)
    partner_user = _user(db, partner)
    album = PhotoAlbum(tenant_id=owner.id, name="Lager", kind="manual")
    db.add(album)
    db.flush()
    files_routes.create_album_share(album.id, AlbumShareCreate(target_tenant_public_id=partner.public_id), db, owner_user)
    files_routes.respond_album_share(album.id, AlbumShareRespond(accept=True), db, partner_user)
    owner_photo = _photo(db, owner.id, exif=datetime(2018, 5, 5, tzinfo=UTC))
    db.add(PhotoAlbumItem(album_id=album.id, file_id=owner_photo.public_id))
    db.commit()

    # Lesen darf der Partner (geteiltes Album), schreiben nie.
    files_routes.access_service.ensure_can_read_stored_file(db, partner_user, owner_photo.id)
    assert files_routes._can_edit_capture_date(partner_user, owner_photo) is False
    with pytest.raises(HTTPException) as exc_info:
        files_routes.update_stored_file_capture_correction(
            owner_photo.public_id, CaptureCorrectionUpdate(corrected_date=date(2020, 1, 1)), db, partner_user
        )
    assert exc_info.value.status_code == 404
    result = files_routes.bulk_update_capture_date(
        FileBulkCaptureDate(file_ids=[owner_photo.public_id], mode="shift", shift_days=1), db, partner_user
    )
    assert result.updated_ids == [] and result.not_found_ids == [owner_photo.public_id]
    db.refresh(owner_photo)
    assert owner_photo.capture_corrected_at is None


# --- Mehrfachauswahl ---------------------------------------------------------------------


def test_bulk_limit_is_enforced():
    ids = [uuid.uuid4() for _ in range(MAX_CAPTURE_DATE_BULK)]
    assert len(FileBulkCaptureDate(file_ids=ids, mode="reset").file_ids) == MAX_CAPTURE_DATE_BULK
    with pytest.raises(ValidationError):
        FileBulkCaptureDate(file_ids=[*ids, uuid.uuid4()], mode="reset")
    with pytest.raises(ValidationError):
        FileBulkCaptureDate(file_ids=[], mode="reset")


def test_bulk_payload_validates_mode_fields():
    with pytest.raises(ValidationError):
        FileBulkCaptureDate(file_ids=[uuid.uuid4()], mode="set")  # Datum fehlt
    with pytest.raises(ValidationError):
        FileBulkCaptureDate(file_ids=[uuid.uuid4()], mode="shift")  # Versatz fehlt
    with pytest.raises(ValidationError):
        FileBulkCaptureDate(file_ids=[uuid.uuid4()], mode="reset", shift_days=2)


def test_bulk_set_applies_the_same_date_to_all(db):
    tenant = make_tenant(db)
    user = _user(db, tenant)
    photos = [_photo(db, tenant.id, exif=datetime(2010, 1, 1, 8, 0, tzinfo=UTC)), _photo(db, tenant.id), _photo(db, tenant.id, estimated=date(1990, 5, 5))]
    result = files_routes.bulk_update_capture_date(
        FileBulkCaptureDate(file_ids=[p.public_id for p in photos], mode="set", corrected_date=date(2024, 8, 1), corrected_time=time(9, 45)), db, user
    )
    assert sorted(result.updated_ids) == sorted(p.public_id for p in photos)
    for photo in photos:
        db.refresh(photo)
        assert effective_capture(photo) == (date(2024, 8, 1), "corrected")
        assert photo.capture_corrected_has_time is True
    (row,) = _audit_rows(db, tenant.id)
    assert row.action == "photo.capture_date_corrected"
    assert row.details_json["updated"] == 3 and row.details_json["has_time"] is True


def test_bulk_shift_moves_by_offset_and_skips_photos_without_date(db):
    tenant = make_tenant(db)
    user = _user(db, tenant)
    with_exif = _photo(db, tenant.id, exif=datetime(2022, 7, 1, 23, 30, tzinfo=UTC))
    estimated = _photo(db, tenant.id, estimated=date(2001, 2, 3))
    no_date = _photo(db, tenant.id)

    result = files_routes.bulk_update_capture_date(
        FileBulkCaptureDate(file_ids=[with_exif.public_id, estimated.public_id, no_date.public_id], mode="shift", shift_days=1, shift_hours=2),
        db,
        user,
    )
    assert result.updated_ids == [with_exif.public_id, estimated.public_id]
    assert result.skipped_no_date_ids == [no_date.public_id]
    db.refresh(with_exif)
    db.refresh(estimated)
    db.refresh(no_date)
    assert with_exif.capture_corrected_at.replace(tzinfo=None) == datetime(2022, 7, 3, 1, 30)
    assert with_exif.capture_corrected_has_time is True
    assert with_exif.exif_taken_at == datetime(2022, 7, 1, 23, 30, tzinfo=UTC)  # Original unverändert
    assert effective_capture(estimated) == (date(2001, 2, 4), "corrected")
    assert estimated.capture_corrected_has_time is False
    assert no_date.capture_corrected_at is None

    # Ein zweites Verschieben setzt auf der Korrektur auf (Kamera nochmals um 1 Tag zurück)
    files_routes.bulk_update_capture_date(FileBulkCaptureDate(file_ids=[with_exif.public_id], mode="shift", shift_days=-1), db, user)
    db.refresh(with_exif)
    assert with_exif.capture_corrected_at.replace(tzinfo=None) == datetime(2022, 7, 2, 1, 30)

    rows = _audit_rows(db, tenant.id)
    assert [row.action for row in rows] == ["photo.capture_date_shifted", "photo.capture_date_shifted"]
    assert rows[0].details_json["skipped_no_date"] == 1
    assert rows[0].details_json["shift_days"] == 1 and rows[0].details_json["shift_hours"] == 2


def test_bulk_shift_into_the_future_is_reported_invalid(db):
    tenant = make_tenant(db)
    user = _user(db, tenant)
    photo = _photo(db, tenant.id, exif=datetime(2020, 1, 1, tzinfo=UTC))
    result = files_routes.bulk_update_capture_date(FileBulkCaptureDate(file_ids=[photo.public_id], mode="shift", shift_days=36500), db, user)
    assert result.invalid_ids == [photo.public_id] and result.updated_ids == []
    db.refresh(photo)
    assert photo.capture_corrected_at is None


def test_bulk_reset_restores_exif_and_reports_unchanged(db):
    tenant = make_tenant(db)
    user = _user(db, tenant)
    corrected = _photo(db, tenant.id, exif=datetime(2015, 4, 4, tzinfo=UTC))
    untouched = _photo(db, tenant.id)
    files_routes.bulk_update_capture_date(FileBulkCaptureDate(file_ids=[corrected.public_id], mode="set", corrected_date=date(2016, 1, 1)), db, user)

    result = files_routes.bulk_update_capture_date(
        FileBulkCaptureDate(file_ids=[corrected.public_id, untouched.public_id], mode="reset"), db, user
    )
    assert result.updated_ids == [corrected.public_id]
    assert result.unchanged_ids == [untouched.public_id]
    db.refresh(corrected)
    assert effective_capture(corrected) == (date(2015, 4, 4), "exif")


# --- Vorrang: Sortierung, Gruppierung, Filter, Termine ----------------------------------------


def test_correction_wins_in_gallery_sort_grouping_and_date_filter(db):
    tenant = make_tenant(db)
    user = _user(db, tenant)
    early = _photo(db, tenant.id, name="a.jpg", exif=datetime(2020, 1, 1, 10, 0, tzinfo=UTC))
    late = _photo(db, tenant.id, name="b.jpg", exif=datetime(2021, 1, 1, 10, 0, tzinfo=UTC))
    same_day = _photo(db, tenant.id, name="c.jpg", exif=datetime(2023, 3, 3, 8, 0, tzinfo=UTC))
    repository = StoredFileRepository()

    def order(**filters):
        rows = repository.list_tenant_files(db, tenant.id, only_images=True, sort_by="group_date", sort_dir="asc", **filters)
        return [(row.original_name, row.group_date, row.date_source) for row in rows]

    assert [name for name, *_ in order()] == ["a.jpg", "b.jpg", "c.jpg"]

    # a.jpg war falsch datiert: korrigiert auf denselben Tag wie c.jpg, aber später am Tag
    files_routes.update_stored_file_capture_correction(
        early.public_id, CaptureCorrectionUpdate(corrected_date=date(2023, 3, 3), corrected_time=time(18, 0)), db, user
    )
    assert order() == [
        ("b.jpg", date(2021, 1, 1), "exif"),
        ("c.jpg", date(2023, 3, 3), "exif"),
        ("a.jpg", date(2023, 3, 3), "corrected"),
    ]
    # Datumsfilter und Zeitstrahl arbeiten mit dem korrigierten Datum
    assert [name for name, *_ in order(date_from=date(2023, 1, 1))] == ["c.jpg", "a.jpg"]
    assert [name for name, *_ in order(date_to=date(2020, 12, 31))] == []
    timeline = {row.day: row.count for row in repository.tenant_files_timeline(db, tenant.id, only_images=True)}
    assert timeline == {date(2021, 1, 1): 1, date(2023, 3, 3): 2}
    assert late.capture_corrected_at is None and same_day.capture_corrected_at is None


def test_correction_relinks_photo_to_matching_termin_and_reset_unlinks(db):
    tenant = make_tenant(db)
    user = _user(db, tenant)
    event = make_event(db, tenant.id, title="Sommerlager", event_date=date(2024, 7, 10), event_end_date=date(2024, 7, 14))
    photo = _photo(db, tenant.id, exif=datetime(2024, 1, 1, 12, 0, tzinfo=UTC))  # falsche Kamerazeit
    gallery_image = db.query(GalleryImage).filter_by(stored_file_id=photo.id).one()
    assert gallery_image.event_id is None

    files_routes.bulk_update_capture_date(FileBulkCaptureDate(file_ids=[photo.public_id], mode="set", corrected_date=date(2024, 7, 12)), db, user)
    db.refresh(gallery_image)
    assert gallery_image.event_id == event.id and gallery_image.event_auto_linked is True
    assert auto_link_date(photo) == date(2024, 7, 12)

    files_routes.bulk_update_capture_date(FileBulkCaptureDate(file_ids=[photo.public_id], mode="reset"), db, user)
    db.refresh(gallery_image)
    assert gallery_image.event_id is None


def test_manual_termin_link_is_never_touched_by_a_correction(db):
    tenant = make_tenant(db)
    user = _user(db, tenant)
    chosen = make_event(db, tenant.id, title="Gewählt", event_date=date(2024, 1, 1))
    make_event(db, tenant.id, title="Datumstreffer", event_date=date(2024, 7, 12))
    photo = _photo(db, tenant.id, exif=datetime(2024, 1, 1, tzinfo=UTC))
    gallery_image = db.query(GalleryImage).filter_by(stored_file_id=photo.id).one()
    gallery_image.event_id = chosen.id
    gallery_image.event_auto_linked = False
    db.flush()

    files_routes.bulk_update_capture_date(FileBulkCaptureDate(file_ids=[photo.public_id], mode="set", corrected_date=date(2024, 7, 12)), db, user)
    db.refresh(gallery_image)
    assert gallery_image.event_id == chosen.id


# --- Export und Freigabe --------------------------------------------------------------------


def _export_meta(**values):
    defaults = dict(
        mime_type="image/jpeg", exif_taken_at=None, estimated_taken_on=None, capture_corrected_at=None, capture_corrected_has_time=False,
        gps_latitude=None, gps_longitude=None, gps_altitude_m=None, gps_direction_deg=None,
    )
    defaults.update(values)
    return SimpleNamespace(**defaults)


def test_export_copy_carries_the_corrected_date_over_a_wrong_exif_date():
    original = jpeg(taken_at=datetime(2001, 1, 1, 0, 0))
    meta = _export_meta(
        exif_taken_at=datetime(2001, 1, 1, tzinfo=UTC), capture_corrected_at=datetime(2023, 5, 6, 7, 8, tzinfo=UTC), capture_corrected_has_time=True
    )
    exported = image_export_service.export_bytes(meta, original)
    assert exported is not None
    _, exif_ifd, _ = read_exif(exported)
    assert exif_ifd[0x9003] == "2023:05:06 07:08:00"
    assert b"hocx:CaptureDateEstimated" not in exported  # Korrektur ist keine Schätzung
    # Ohne Uhrzeit: Mittag-Konvention
    date_only = image_export_service.export_bytes(
        _export_meta(capture_corrected_at=datetime(2023, 5, 6, 12, 0, tzinfo=UTC)), jpeg()
    )
    assert read_exif(date_only)[1][0x9003] == "2023:05:06 12:00:00"


def test_share_page_moment_prefers_correction():
    exif = datetime(2001, 1, 1, tzinfo=UTC)
    corrected = datetime(2023, 5, 6, 12, 0, tzinfo=UTC)
    assert effective_capture_moment(SimpleNamespace(exif_taken_at=exif, capture_corrected_at=corrected)) == corrected
    assert effective_capture_moment(SimpleNamespace(exif_taken_at=exif, capture_corrected_at=None)) == exif
