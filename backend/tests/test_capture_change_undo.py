"""Relative Datumskorrektur mit Minuten, Vorschau, Rückgängig und gezielter Termin-Neuzuordnung
(Plan «Upload-Verlauf» 7, Migration 0251)."""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text

from app.api.routes import files as files_routes
from app.models.entities import GalleryImage, StoredFile
from app.models.upload_history_entities import CaptureChangeBatch, CaptureChangeItem
from app.schemas.files import FileBulkCaptureDate
from app.services import photo_event_link_service
from tests.factories import make_app_user, make_current_user, make_event, make_tenant


def _user(db, tenant, role="writer"):
    account = make_app_user(db, email=f"{uuid.uuid4().hex[:10]}@example.com", tenant_id=tenant.id, role_code=role)
    return make_current_user(tenant.id, role=role, user_id=account.id)


def _photo(db, tenant_id, *, exif=None, estimated=None, event=None, auto=True):
    stored = StoredFile(
        tenant_id=tenant_id, original_name=f"{uuid.uuid4().hex[:6]}.jpg", mime_type="image/jpeg",
        storage_path=f"uploads/{uuid.uuid4().hex}.jpg", exif_taken_at=exif, estimated_taken_on=estimated,
        metadata_scanned_at=datetime.now(UTC),
    )
    db.add(stored)
    db.flush()
    db.add(GalleryImage(tenant_id=tenant_id, stored_file_id=stored.id, event_id=event.id if event else None, event_auto_linked=bool(event) and auto))
    db.flush()
    return stored


def _shift(db, user, ids, **values):
    payload = FileBulkCaptureDate(file_ids=ids, mode="shift", **values)
    return files_routes.bulk_update_capture_date(payload, db=db, user=user)


def _preview(db, user, ids, **values):
    return files_routes.preview_bulk_capture_date(FileBulkCaptureDate(file_ids=ids, mode="shift", **values), db=db, user=user)


def _naive(value):
    return value.astimezone(UTC).replace(tzinfo=None)


def test_minutes_shift_earlier_and_repeated_shifts_sum_up(db):
    tenant = make_tenant(db)
    user = _user(db, tenant)
    photo = _photo(db, tenant.id, exif=datetime(2026, 5, 2, 10, 0, tzinfo=UTC))
    _shift(db, user, [photo.public_id], shift_hours=-1, shift_minutes=-15)
    db.refresh(photo)
    assert _naive(photo.capture_corrected_at) == datetime(2026, 5, 2, 8, 45)
    _shift(db, user, [photo.public_id], shift_minutes=5)
    db.refresh(photo)
    assert _naive(photo.capture_corrected_at) == datetime(2026, 5, 2, 8, 50)
    assert _naive(photo.exif_taken_at) == datetime(2026, 5, 2, 10, 0)


def test_preview_writes_nothing_and_matches_apply(db):
    tenant = make_tenant(db)
    user = _user(db, tenant)
    with_time = _photo(db, tenant.id, exif=datetime(2026, 5, 2, 23, 30, tzinfo=UTC))
    date_only = _photo(db, tenant.id, estimated=date(2026, 5, 2))
    no_date = _photo(db, tenant.id)
    ids = [with_time.public_id, date_only.public_id, no_date.public_id, uuid.uuid4()]
    preview = _preview(db, user, ids, shift_hours=1, shift_minutes=15)
    db.refresh(with_time)
    assert with_time.capture_corrected_at is None
    assert (preview.will_change, preview.no_date, preview.date_only_unchanged, preview.not_found) == (1, 1, 1, 1)
    assert preview.no_date_ids == [no_date.public_id]
    assert preview.day_changes == 1  # 23:30 + 1:15 → nächster Tag
    assert preview.samples[0].after.replace(tzinfo=None) == datetime(2026, 5, 3, 0, 45)
    applied = _shift(db, user, ids, shift_hours=1, shift_minutes=15)
    assert len(applied.updated_ids) == preview.will_change
    assert len(applied.skipped_no_date_ids) == preview.no_date
    assert len(applied.no_time_unchanged_ids) == preview.date_only_unchanged


def test_preview_reports_event_transitions_only_for_auto_linked_photos(db):
    tenant = make_tenant(db)
    user = _user(db, tenant)
    training = make_event(db, tenant_id=tenant.id, title="Training", event_date=date(2026, 5, 2))
    auto = _photo(db, tenant.id, exif=datetime(2026, 5, 2, 9, 0, tzinfo=UTC), event=training)
    manual = _photo(db, tenant.id, exif=datetime(2026, 5, 2, 9, 0, tzinfo=UTC), event=training, auto=False)
    preview = _preview(db, user, [auto.public_id, manual.public_id], shift_days=1)
    assert preview.event_changes == 1
    assert preview.event_transitions[0].from_event.title == "Training" and preview.event_transitions[0].to_event is None


def test_undo_restores_exactly_and_skips_changed_photos(db):
    tenant = make_tenant(db)
    user = _user(db, tenant)
    plain = _photo(db, tenant.id, exif=datetime(2026, 5, 2, 10, 0, tzinfo=UTC))
    corrected = _photo(db, tenant.id, exif=datetime(2026, 5, 2, 11, 0, tzinfo=UTC))
    corrected.capture_corrected_at = datetime(2026, 5, 2, 12, 0, tzinfo=UTC)
    corrected.capture_corrected_has_time = True
    touched_later = _photo(db, tenant.id, exif=datetime(2026, 5, 2, 13, 0, tzinfo=UTC))
    db.flush()
    result = _shift(db, user, [plain.public_id, corrected.public_id, touched_later.public_id], shift_minutes=-30)
    assert result.batch_id is not None
    # Danach von Hand anders gesetzt → beim Rückgängig «inzwischen geändert»
    _shift(db, user, [touched_later.public_id], shift_minutes=10)
    undone = files_routes.undo_capture_change(result.batch_id, db=db, user=user)
    assert set(undone.restored_ids) == {plain.public_id, corrected.public_id}
    assert undone.conflict_ids == [touched_later.public_id]
    for photo in (plain, corrected):
        db.refresh(photo)
    assert plain.capture_corrected_at is None and plain.capture_file_state == "pending"  # Original zurück in die Datei
    assert _naive(corrected.capture_corrected_at) == datetime(2026, 5, 2, 12, 0)
    with pytest.raises(HTTPException) as caught:
        files_routes.undo_capture_change(result.batch_id, db=db, user=user)
    assert caught.value.status_code == 409
    action = db.execute(text("SELECT details_json FROM audit_log WHERE tenant_id = :t AND action = 'photo.capture_date_shift_undone'"), {"t": tenant.id}).scalar_one()
    assert action["restored"] == 2


def test_chunked_calls_share_one_batch_and_foreign_batches_are_404(db):
    tenant, other = make_tenant(db), make_tenant(db)
    user, colleague = _user(db, tenant), _user(db, tenant)
    stranger = _user(db, other)
    first, second = (_photo(db, tenant.id, exif=datetime(2026, 5, 2, 10, i, tzinfo=UTC)) for i in range(2))
    chunk = _shift(db, user, [first.public_id], shift_minutes=7)
    again = _shift(db, user, [second.public_id], shift_minutes=7, batch_id=chunk.batch_id)
    assert again.batch_id == chunk.batch_id
    assert db.scalar(select(CaptureChangeBatch.updated_count).where(CaptureChangeBatch.id == chunk.batch_id)) == 2
    for other_user in (colleague,):
        with pytest.raises(HTTPException) as caught:
            _shift(db, other_user, [second.public_id], shift_minutes=7, batch_id=chunk.batch_id)
        assert caught.value.status_code == 404
    with pytest.raises(HTTPException) as caught:
        files_routes.undo_capture_change(chunk.batch_id, db=db, user=stranger)
    assert caught.value.status_code == 404


def test_resync_only_on_day_change_and_manual_link_stays(db):
    tenant = make_tenant(db)
    user = _user(db, tenant)
    saturday = make_event(db, tenant_id=tenant.id, title="Samstag", event_date=date(2026, 5, 2))
    sunday = make_event(db, tenant_id=tenant.id, title="Sonntag", event_date=date(2026, 5, 3))
    auto = _photo(db, tenant.id, exif=datetime(2026, 5, 2, 23, 0, tzinfo=UTC), event=saturday)
    manual = _photo(db, tenant.id, exif=datetime(2026, 5, 2, 23, 0, tzinfo=UTC), event=saturday, auto=False)
    calls = []
    original = photo_event_link_service.resync_photos_after_date_change

    def spy(db_, tenant_id, files):
        calls.append(len(files))
        return original(db_, tenant_id, files)

    photo_event_link_service.resync_photos_after_date_change = spy
    try:
        _shift(db, user, [auto.public_id, manual.public_id], shift_minutes=30)  # 23:30, gleicher Tag
        _shift(db, user, [auto.public_id, manual.public_id], shift_hours=1)  # 00:30 am Sonntag
    finally:
        photo_event_link_service.resync_photos_after_date_change = original
    assert calls == [0, 2]
    links = dict(db.execute(select(GalleryImage.stored_file_id, GalleryImage.event_id).where(GalleryImage.stored_file_id.in_([auto.id, manual.id]))).all())
    assert links[auto.id] == sunday.id and links[manual.id] == saturday.id


def test_undo_is_bound_to_the_files(db):
    tenant = make_tenant(db)
    user = _user(db, tenant)
    photo = _photo(db, tenant.id, exif=datetime(2026, 5, 2, 10, 0, tzinfo=UTC))
    result = _shift(db, user, [photo.public_id], shift_minutes=3)
    db.execute(text("DELETE FROM gallery_image WHERE stored_file_id = :id"), {"id": photo.id})
    db.execute(text("DELETE FROM stored_file WHERE id = :id"), {"id": photo.id})
    db.flush()
    db.expire_all()
    assert db.get(CaptureChangeBatch, result.batch_id) is None
    assert db.scalar(select(CaptureChangeItem.id).where(CaptureChangeItem.batch_id == result.batch_id)) is None


def _document(db, tenant_id):
    stored = StoredFile(
        tenant_id=tenant_id, original_name=f"{uuid.uuid4().hex[:6]}.pdf", mime_type="application/pdf",
        storage_path=f"uploads/{uuid.uuid4().hex}.pdf",
    )
    db.add(stored)
    db.flush()
    db.add(GalleryImage(tenant_id=tenant_id, stored_file_id=stored.id))
    db.flush()
    return stored


def _set(db, user, ids, **values):
    payload = FileBulkCaptureDate(file_ids=ids, mode="set", **values)
    return files_routes.bulk_update_capture_date(payload, db=db, user=user)


def test_set_date_for_files_of_an_upload_job_reports_documents_and_can_be_undone(db):
    """«Datum setzen» (Upload-Verlauf 1.6): festes Datum mit Uhrzeit für Fotos eines Vorgangs,
    Dokumente bleiben unverändert und werden gemeldet, Rückgängig wie beim Verschieben, Audit mit
    Vorgang. Fremde Fotos kommen wie unbekannte als not_found zurück und bleiben unverändert."""
    from app.services import upload_job_service

    tenant, other = make_tenant(db), make_tenant(db)
    user = _user(db, tenant)
    job = upload_job_service.open_job(db, tenant_id=tenant.id, channel="gallery", created_by=user.user_id, status="done")
    with_exif = _photo(db, tenant.id, exif=datetime(2026, 5, 2, 10, 0, tzinfo=UTC))
    without = _photo(db, tenant.id)
    document = _document(db, tenant.id)
    foreign = _photo(db, other.id, exif=datetime(2026, 5, 2, 10, 0, tzinfo=UTC))
    ids = [with_exif.public_id, without.public_id, document.public_id, foreign.public_id]

    preview = files_routes.preview_bulk_capture_date(
        FileBulkCaptureDate(file_ids=ids, mode="set", corrected_date=date(2026, 6, 1), corrected_time=None), db=db, user=user
    )
    assert (preview.will_change, preview.not_image, preview.not_found) == (2, 1, 1)

    from datetime import time as dtime

    result = _set(db, user, ids, corrected_date=date(2026, 6, 1), corrected_time=dtime(14, 30), upload_job_id=job.id)
    assert set(result.updated_ids) == {with_exif.public_id, without.public_id}
    assert result.skipped_not_image_ids == [document.public_id]
    assert result.not_found_ids == [foreign.public_id]
    for photo in (with_exif, without, foreign):
        db.refresh(photo)
    assert _naive(with_exif.capture_corrected_at) == datetime(2026, 6, 1, 14, 30) and with_exif.capture_corrected_has_time
    assert foreign.capture_corrected_at is None
    batch = db.get(CaptureChangeBatch, result.batch_id)
    assert batch.mode == "set" and batch.upload_job_id == job.id and batch.updated_count == 2
    audit = db.execute(
        text("SELECT details_json FROM audit_log WHERE tenant_id = :t AND action = 'photo.capture_date_corrected'"), {"t": tenant.id}
    ).scalar_one()
    assert audit["upload_job_id"] == str(job.id) and audit["skipped_not_image"] == 1
    assert str(foreign.public_id) not in audit["file_ids"]

    undone = files_routes.undo_capture_change(result.batch_id, db=db, user=user)
    assert set(undone.restored_ids) == {with_exif.public_id, without.public_id}
    db.refresh(with_exif)
    db.refresh(without)
    assert with_exif.capture_corrected_at is None and without.capture_corrected_at is None
    undo_audit = db.execute(
        text("SELECT details_json FROM audit_log WHERE tenant_id = :t AND action = 'photo.capture_date_shift_undone'"), {"t": tenant.id}
    ).scalar_one()
    assert undo_audit["mode"] == "set" and undo_audit["upload_job_id"] == str(job.id)


def test_set_date_without_files_manage_lists_documents_as_not_found(db):
    """Dokumente meldet nur, wer die Ablage verwalten darf (Regel wie bulk-tags)."""
    tenant = make_tenant(db)
    user = _user(db, tenant)
    document = _document(db, tenant.id)
    restricted = make_current_user(tenant.id, role="writer", user_id=user.user_id, permissions=frozenset({"photos.manage", "photos.read"}))
    result = _set(db, restricted, [document.public_id], corrected_date=date(2026, 6, 1))
    assert result.skipped_not_image_ids == [] and result.not_found_ids == [document.public_id]


def test_set_date_needs_photos_manage_and_rejects_a_foreign_upload_job(db):
    tenant, other = make_tenant(db), make_tenant(db)
    reader = _user(db, tenant, role="reader")
    photo = _photo(db, tenant.id, exif=datetime(2026, 5, 2, 10, 0, tzinfo=UTC))
    with pytest.raises(HTTPException) as caught:
        _set(db, reader, [photo.public_id], corrected_date=date(2026, 6, 1))
    assert caught.value.status_code == 403
    from app.services import upload_job_service

    foreign_job = upload_job_service.open_job(db, tenant_id=other.id, channel="gallery", created_by=None, status="done")
    writer = _user(db, tenant)
    with pytest.raises(HTTPException) as caught:
        _set(db, writer, [photo.public_id], corrected_date=date(2026, 6, 1), upload_job_id=foreign_job.id)
    assert caught.value.status_code == 404
    db.refresh(photo)
    assert photo.capture_corrected_at is None
