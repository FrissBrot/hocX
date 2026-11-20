"""Korrigiertes Aufnahmedatum in der Datei (Migration 0203): Schreiber (exif_date_write) für JPEG,
PNG, WebP, HEIC, Big-/Little-Endian, Wiederherstellen byte-identisch, manipulierte Dateien - und der
Job capture_date_file_sync (pending -> written, Wiederherstellen, Rennen, Papierkorb, Virenstatus,
Mandanten, Fehler) samt Schutz des EXIF-Originals vor erneutem Einlesen."""

from __future__ import annotations

import hashlib
import io
import random
import struct
import uuid
import zlib
from datetime import UTC, date, datetime, time
from types import SimpleNamespace

import pytest
from PIL import Image
from sqlalchemy import select, text

from app.api.routes import files as files_routes
from app.core.config import settings
from app.core.storage import MAIN, get_object_store
from app.models.entities import GalleryImage, StoredFile
from app.schemas.files import CaptureCorrectionUpdate, FileBulkCaptureDate
from app.services import capture_date_file_sync, image_export_service, image_metadata_service
from app.services.capture_date import corrected_exif_stamp, effective_capture
from app.services.exif_date_write import (
    TAG_DATETIME,
    TAG_DATETIME_DIGITIZED,
    TAG_DATETIME_ORIGINAL,
    ExifDateError,
    ExifDateUnsupported,
    parse_original,
    read_date_values,
    restore_capture_date,
    write_capture_date,
)
from app.services.file_service import FileService
from tests.factories import make_app_user, make_current_user, make_tenant
from tests.image_fixtures import jpeg, png, read_exif, webp

STAMP = "2021:06:05 14:15:00"
ORIGINAL = datetime(2019, 3, 4, 10, 30, 0)


def _pixels(data: bytes) -> bytes:
    with Image.open(io.BytesIO(data)) as image:
        return image.convert("RGB").tobytes()


def _dto(data: bytes) -> str | None:
    return read_exif(data)[1].get(TAG_DATETIME_ORIGINAL)


def _png_crcs_valid(data: bytes) -> bool:
    position = 8
    while position + 12 <= len(data):
        (length,) = struct.unpack_from(">I", data, position)
        end = position + 8 + length
        if end + 4 > len(data):
            return False
        (crc,) = struct.unpack_from(">I", data, end)
        if zlib.crc32(data[position + 4:end]) & 0xFFFFFFFF != crc:
            return False
        if data[position + 4:position + 8] == b"IEND":
            return True
        position = end + 4
    return False


def _heif(**exif_values) -> bytes:
    from tests.image_fixtures import build_exif

    buffer = io.BytesIO()
    Image.new("RGB", (32, 24), (10, 20, 30)).save(buffer, format="HEIF", exif=build_exif(**exif_values).tobytes())
    return buffer.getvalue()


def _big_endian_jpeg() -> bytes:
    """JPEG mit "MM"-EXIF (Motorola): IFD0 DateTime + Exif-IFD DateTimeOriginal/Digitized."""
    plain = jpeg()
    values = [b"2019:03:04 10:30:00\x00", b"2019:03:04 10:30:01\x00", b"2019:03:04 10:30:02\x00"]
    ifd0_at, exif_at = 8, 8 + 2 + 2 * 12 + 4
    values_at = exif_at + 2 + 2 * 12 + 4
    tiff = bytearray(b"MM\x00*" + struct.pack(">I", ifd0_at))
    tiff += struct.pack(">H", 2)
    tiff += struct.pack(">HHII", TAG_DATETIME, 2, 20, values_at)
    tiff += struct.pack(">HHII", 0x8769, 4, 1, exif_at) + struct.pack(">I", 0)
    tiff += struct.pack(">H", 2)
    tiff += struct.pack(">HHII", TAG_DATETIME_ORIGINAL, 2, 20, values_at + 20)
    tiff += struct.pack(">HHII", TAG_DATETIME_DIGITIZED, 2, 20, values_at + 40)
    tiff += struct.pack(">I", 0) + b"".join(values)
    payload = b"Exif\x00\x00" + bytes(tiff)
    segment = b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload
    return plain[:2] + segment + plain[2:]


# --- Schreiber ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "build",
    [
        lambda: jpeg(taken_at=ORIGINAL),
        _big_endian_jpeg,
        lambda: png(taken_at=ORIGINAL),
        lambda: webp(taken_at=ORIGINAL),
        lambda: _heif(taken_at=ORIGINAL),
    ],
    ids=["jpeg-le", "jpeg-be", "png", "webp", "heic"],
)
def test_inplace_write_and_byte_identical_restore(build):
    original = build()
    written, record = write_capture_date(original, STAMP, record_original=True)

    assert len(written) == len(original)
    assert record["mode"] == "inplace" and record["slots"]
    assert all(raw.rstrip(b"\x00") == STAMP.encode() for _b, _t, raw in read_date_values(written))
    assert _dto(written) == STAMP
    assert _pixels(written) == _pixels(original)
    if original.startswith(b"\x89PNG"):
        assert _png_crcs_valid(written)

    # Eine weitere Korrektur speichert kein zweites Original ...
    again, second = write_capture_date(written, "2022:01:02 03:04:05", record_original=False)
    assert second is None and _dto(again) == "2022:01:02 03:04:05"
    # ... und das Wiederherstellen ergibt die Originaldatei byte-genau.
    assert restore_capture_date(again, parse_original(record)) == original


def test_big_endian_writes_all_three_date_tags():
    written, record = write_capture_date(_big_endian_jpeg(), STAMP, record_original=True)
    assert {slot["t"] for slot in record["slots"]} == {TAG_DATETIME, TAG_DATETIME_ORIGINAL, TAG_DATETIME_DIGITIZED}
    exif, exif_ifd, _gps = read_exif(written)
    assert exif[TAG_DATETIME] == STAMP and exif_ifd[TAG_DATETIME_DIGITIZED] == STAMP


def test_heif_exif_item_without_marker_is_found():
    original = _heif(taken_at=ORIGINAL)
    marker = original.find(b"\x00\x00\x00\x06Exif\x00\x00")
    variant = original[:marker] + b"\x00\x00\x00\x06" + b"\x00" * 6 + original[marker + 10:]
    written, record = write_capture_date(variant, STAMP, record_original=True)
    assert _dto(written) == STAMP
    assert restore_capture_date(written, record) == variant


def test_jpeg_without_exif_gets_a_segment_that_restore_removes_again():
    original = jpeg()
    written, record = write_capture_date(original, STAMP, record_original=True)

    assert record["mode"] == "inserted"
    assert _dto(written) == STAMP and _pixels(written) == _pixels(original)
    later, none = write_capture_date(written, "2020:02:02 12:00:00", record_original=False)
    assert none is None and _dto(later) == "2020:02:02 12:00:00"
    assert restore_capture_date(later, record) == original


def test_jpeg_with_exif_but_without_capture_date_keeps_other_values():
    original = jpeg(make="Scanner AG", orientation=6)
    written, record = write_capture_date(original, STAMP, record_original=True)

    assert record["mode"] == "replaced"
    exif, exif_ifd, _gps = read_exif(written)
    assert exif_ifd[TAG_DATETIME_ORIGINAL] == STAMP and exif[0x010F] == "Scanner AG" and exif[0x0112] == 6
    assert _pixels(written) == _pixels(original)
    assert restore_capture_date(written, record) == original


@pytest.mark.parametrize("build", [lambda: png(), lambda: webp(), lambda: _heif(make="X"), lambda: b"GIF89a" + b"\x00" * 40])
def test_formats_without_capture_date_are_unsupported(build):
    with pytest.raises(ExifDateUnsupported):
        write_capture_date(build(), STAMP, record_original=True)


def test_written_date_vanished_is_an_error_not_a_guess():
    with pytest.raises(ExifDateError):
        write_capture_date(jpeg(), STAMP, record_original=False)


def test_restore_refuses_records_that_do_not_fit():
    original = jpeg(taken_at=ORIGINAL)
    written, record = write_capture_date(original, STAMP, record_original=True)
    for bad in (None, {}, {"v": 1, "mode": "x"}, {"v": 1, "mode": "inplace", "slots": [{"b": 99, "t": TAG_DATETIME_ORIGINAL, "raw": "00" * 20}]},
                {"v": 1, "mode": "inplace", "slots": [{"b": 0, "t": 0x0110, "raw": "00" * 20}]},
                {"v": 1, "mode": "replaced", "segment": "nicht-base64!"}, {"v": 1, "mode": "inserted", "length": 10**6}):
        with pytest.raises(ExifDateError):
            restore_capture_date(written, bad)
    # Passt die Datei nicht mehr (Feldlänge anders), wird nichts halb zurückgeschrieben.
    tampered = dict(record, slots=[dict(record["slots"][0], raw="00" * 21)])
    with pytest.raises(ExifDateError):
        restore_capture_date(written, tampered)
    inserted_record = {"v": 1, "mode": "inserted", "length": 106}
    with pytest.raises(ExifDateError):
        restore_capture_date(png(), inserted_record)


def test_manipulated_files_never_raise_anything_else():
    rng = random.Random(4711)
    samples = [jpeg(taken_at=ORIGINAL), _big_endian_jpeg(), png(taken_at=ORIGINAL), webp(taken_at=ORIGINAL), jpeg(make="M")]
    # Gezielte Fälle: riesige Eintragszahl, Werte ausserhalb des Blocks, abgeschnittene Datei.
    huge_count = bytearray(_big_endian_jpeg())
    ifd0 = huge_count.find(b"MM\x00*") + 8
    huge_count[ifd0:ifd0 + 2] = b"\xff\xff"
    samples.append(bytes(huge_count))
    out_of_bounds = bytearray(_big_endian_jpeg())
    entry = out_of_bounds.find(b"MM\x00*") + 8 + 2
    out_of_bounds[entry + 8:entry + 12] = b"\x7f\xff\xff\xff"
    samples.append(bytes(out_of_bounds))
    samples.append(jpeg(taken_at=ORIGINAL)[:120])
    for sample in list(samples):
        for _ in range(150):
            mutated = bytearray(sample)
            for _flip in range(rng.randint(1, 8)):
                mutated[rng.randrange(len(mutated))] = rng.randrange(256)
            samples.append(bytes(mutated))
    for sample in samples:
        try:
            written, record = write_capture_date(sample, STAMP, record_original=True)
        except (ExifDateUnsupported, ExifDateError):
            continue
        assert record is not None
        if record["mode"] == "inplace":
            assert len(written) == len(sample)
            restored = restore_capture_date(written, record)
            # Datumsfelder byte-identisch; ganze Datei nur, wenn ihre PNG-CRCs vorher stimmten.
            assert read_date_values(restored) == read_date_values(sample)
            if not sample.startswith(b"\x89PNG") or _png_crcs_valid(sample):
                assert restored == sample


def test_corrected_stamp_keeps_the_original_time_without_a_corrected_time():
    with_time = SimpleNamespace(capture_corrected_at=datetime(2021, 6, 5, 14, 15, tzinfo=UTC), capture_corrected_has_time=True, exif_taken_at=None)
    assert corrected_exif_stamp(with_time) == "2021:06:05 14:15:00"
    date_only = SimpleNamespace(
        capture_corrected_at=datetime(2021, 6, 5, 12, 0, tzinfo=UTC), capture_corrected_has_time=False,
        exif_taken_at=datetime(2019, 3, 4, 10, 30, 7, tzinfo=UTC),
    )
    assert corrected_exif_stamp(date_only) == "2021:06:05 10:30:07"
    no_original = SimpleNamespace(capture_corrected_at=datetime(2021, 6, 5, 12, 0, tzinfo=UTC), capture_corrected_has_time=False, exif_taken_at=None)
    assert corrected_exif_stamp(no_original) == "2021:06:05 12:00:00"
    assert corrected_exif_stamp(SimpleNamespace(capture_corrected_at=None)) is None


# --- Job ----------------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolated_storage(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(settings, "upload_root", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "thumbnail_root", str(tmp_path / "thumbnails"))


def _user(db, tenant):
    app_user = make_app_user(db, email=f"{uuid.uuid4().hex[:10]}@example.com", tenant_id=tenant.id, role_code="writer")
    return make_current_user(tenant.id, role="writer", user_id=app_user.id)


def _photo(db, tenant_id, content: bytes, *, exif=ORIGINAL, mime="image/jpeg", scanned=True) -> StoredFile:
    key = f"uploads/tenant-{tenant_id}/gallery/{uuid.uuid4().hex}.{mime.split('/')[1]}"
    get_object_store().put_bytes(db, MAIN, key, content, content_type=mime)
    stored_file = StoredFile(
        tenant_id=tenant_id,
        original_name="foto.jpg",
        mime_type=mime,
        storage_path=key,
        file_size_bytes=len(content),
        checksum_sha256=hashlib.sha256(content).hexdigest(),
        exif_taken_at=exif.replace(tzinfo=UTC) if exif else None,
        metadata_scanned_at=datetime.now(UTC) if scanned else None,
    )
    db.add(stored_file)
    db.flush()
    db.add(GalleryImage(tenant_id=tenant_id, stored_file_id=stored_file.id))
    db.commit()
    return stored_file


def _content(stored_file: StoredFile) -> bytes:
    return get_object_store().get_bytes(MAIN, stored_file.storage_path)


def _correct(db, user, photo, day=date(2021, 6, 5), at: time | None = time(14, 15)):
    return files_routes.update_stored_file_capture_correction(
        photo.public_id, CaptureCorrectionUpdate(corrected_date=day, corrected_time=at), db, user
    )


def _reset(db, user, photo):
    return files_routes.update_stored_file_capture_correction(photo.public_id, CaptureCorrectionUpdate(corrected_date=None), db, user)


def test_job_writes_the_correction_and_restore_brings_back_the_original_file(db):
    tenant = make_tenant(db)
    user = _user(db, tenant)
    original = jpeg(taken_at=ORIGINAL)
    photo = _photo(db, tenant.id, original)
    original_key, original_checksum = photo.storage_path, photo.checksum_sha256

    metadata = _correct(db, user, photo)
    # Die Anzeige gilt sofort, bevor die Datei geschrieben ist.
    assert metadata.date_source == "corrected" and metadata.effective_date == date(2021, 6, 5)
    assert metadata.capture_file_state == "pending"
    db.refresh(photo)
    assert photo.capture_file_state == "pending" and _content(photo) == original

    result = capture_date_file_sync.process_pending(db)
    assert result["written"] == 1
    db.refresh(photo)
    assert photo.capture_file_state == "written"
    assert photo.storage_path != original_key
    written = _content(photo)
    assert _dto(written) == "2021:06:05 14:15:00"
    assert photo.checksum_sha256 == hashlib.sha256(written).hexdigest() != original_checksum
    assert photo.file_size_bytes == len(written)
    assert photo.source_checksum_sha256 == original_checksum  # Original bleibt als Duplikat erkennbar
    assert photo.exif_taken_at.replace(tzinfo=None) == ORIGINAL  # Original in hocX unverändert
    assert photo.capture_exif_original["mode"] == "inplace"
    # Altes Objekt ist zum Löschen vorgemerkt (Tombstone, physisch durch storage_purge).
    assert db.execute(
        text("SELECT status = 'deleted' FROM storage_object WHERE namespace = 'main' AND key = :key"), {"key": original_key}
    ).scalar()

    # Datei trägt das Datum schon: die Exportkopie fasst es nicht mehr an.
    assert image_export_service._wants_date(photo) is None

    # Erneute Analyse der Datei (Backfill, Vorab-Abgleich) übernimmt das hocX-Datum nie als Original.
    image_metadata_service.apply_server_analysis(photo, image_metadata_service.extract_image_metadata(written), source="backfill")
    assert photo.exif_taken_at.replace(tzinfo=None) == ORIGINAL

    reset = _reset(db, user, photo)
    assert reset.date_source == "exif" and reset.effective_date == ORIGINAL.date()  # sofort
    assert capture_date_file_sync.process_pending(db)["restored"] == 1
    db.refresh(photo)
    assert photo.capture_file_state is None and photo.capture_exif_original is None
    assert _content(photo) == original
    assert photo.checksum_sha256 == original_checksum


def test_date_only_correction_keeps_the_original_time_in_the_file(db):
    tenant = make_tenant(db)
    user = _user(db, tenant)
    photo = _photo(db, tenant.id, jpeg(taken_at=ORIGINAL))
    _correct(db, user, photo, day=date(2020, 1, 2), at=None)
    capture_date_file_sync.process_pending(db)
    db.refresh(photo)
    assert _dto(_content(photo)) == "2020:01:02 10:30:00"


def test_bulk_shift_marks_all_pending_and_job_writes_each(db):
    tenant = make_tenant(db)
    user = _user(db, tenant)
    photos = [_photo(db, tenant.id, jpeg(taken_at=ORIGINAL, color=(index, 0, 0))) for index in range(3)]
    files_routes.bulk_update_capture_date(
        FileBulkCaptureDate(file_ids=[photo.public_id for photo in photos], mode="shift", shift_days=1, shift_hours=2), db, user
    )
    assert capture_date_file_sync.process_pending(db)["written"] == 3
    for photo in photos:
        db.refresh(photo)
        assert _dto(_content(photo)) == "2019:03:05 12:30:00"


def test_correction_then_restore_before_the_job_leaves_the_file_untouched(db):
    tenant = make_tenant(db)
    user = _user(db, tenant)
    original = jpeg(taken_at=ORIGINAL)
    photo = _photo(db, tenant.id, original)
    key = photo.storage_path
    _correct(db, user, photo)
    _reset(db, user, photo)

    assert capture_date_file_sync.process_pending(db)["nothing"] == 1
    db.refresh(photo)
    assert photo.capture_file_state is None and photo.storage_path == key and _content(photo) == original


def test_second_correction_after_writing_keeps_the_first_original(db):
    tenant = make_tenant(db)
    user = _user(db, tenant)
    original = jpeg(taken_at=ORIGINAL)
    photo = _photo(db, tenant.id, original)
    _correct(db, user, photo)
    capture_date_file_sync.process_pending(db)
    db.refresh(photo)
    first_record = photo.capture_exif_original
    _correct(db, user, photo, day=date(2022, 2, 2), at=time(8, 0))
    capture_date_file_sync.process_pending(db)
    db.refresh(photo)
    assert photo.capture_exif_original == first_record
    assert _dto(_content(photo)) == "2022:02:02 08:00:00"
    _reset(db, user, photo)
    capture_date_file_sync.process_pending(db)
    db.refresh(photo)
    assert _content(photo) == original


def test_jpeg_without_date_gets_inserted_segment_and_exif_original_stays_empty(db):
    tenant = make_tenant(db)
    user = _user(db, tenant)
    original = jpeg()
    photo = _photo(db, tenant.id, original, exif=None)
    _correct(db, user, photo)
    capture_date_file_sync.process_pending(db)
    db.refresh(photo)
    assert photo.capture_exif_original["mode"] == "inserted"
    written = _content(photo)
    assert _dto(written) == "2021:06:05 14:15:00"

    # Weder Backfill/Vorab-Abgleich noch die Metadatenanzeige halten das hocX-Datum für das Original.
    photo.metadata_scanned_at = None
    image_metadata_service.apply_server_analysis(photo, image_metadata_service.extract_image_metadata(written), source="backfill")
    assert photo.exif_taken_at is None
    photo.metadata_scanned_at = None
    db.flush()
    metadata = FileService().get_stored_file_metadata(db, photo, settings.storage_root, tenant.id, can_edit=True)
    assert metadata.exif_taken_at is None and metadata.date_source == "corrected"
    photo.metadata_scanned_at = datetime.now(UTC)
    db.commit()

    _reset(db, user, photo)
    capture_date_file_sync.process_pending(db)
    db.refresh(photo)
    assert _content(photo) == original
    assert effective_capture(photo)[1] == "upload"


def test_never_analysed_file_is_analysed_before_the_first_write(db):
    tenant = make_tenant(db)
    user = _user(db, tenant)
    photo = _photo(db, tenant.id, jpeg(taken_at=ORIGINAL), exif=None, scanned=False)
    _correct(db, user, photo)
    capture_date_file_sync.process_pending(db)
    db.refresh(photo)
    assert photo.metadata_scanned_at is not None
    assert photo.exif_taken_at.replace(tzinfo=None) == ORIGINAL  # aus der Datei VOR dem Schreiben


def test_unsupported_format_keeps_file_and_db_correction(db):
    tenant = make_tenant(db)
    user = _user(db, tenant)
    original = png()
    photo = _photo(db, tenant.id, original, exif=None, mime="image/png")
    key = photo.storage_path
    _correct(db, user, photo)
    assert capture_date_file_sync.process_pending(db)["unsupported"] == 1
    db.refresh(photo)
    assert photo.capture_file_state == "unsupported" and photo.storage_path == key and _content(photo) == original
    assert effective_capture(photo) == (date(2021, 6, 5), "corrected")
    # Zurücksetzen: nichts in der Datei zurückzuschreiben.
    _reset(db, user, photo)
    capture_date_file_sync.process_pending(db)
    db.refresh(photo)
    assert photo.capture_file_state is None


def test_trash_and_unscanned_files_are_skipped(db):
    tenant = make_tenant(db)
    user = _user(db, tenant)
    trashed = _photo(db, tenant.id, jpeg(taken_at=ORIGINAL))
    unscanned = _photo(db, tenant.id, jpeg(taken_at=ORIGINAL, color=(1, 2, 3)))
    _correct(db, user, trashed)
    _correct(db, user, unscanned)
    db.execute(text("UPDATE stored_file SET deleted_at = now() WHERE id = :id"), {"id": trashed.id})
    db.execute(text("UPDATE stored_file SET scan_status = 'pending' WHERE id = :id"), {"id": unscanned.id})
    db.commit()

    assert capture_date_file_sync.process_pending(db) == {"written": 0, "restored": 0, "unsupported": 0, "nothing": 0, "failed": 0}
    states = dict(db.execute(text("SELECT id, capture_file_state FROM stored_file WHERE id IN (:a, :b)"), {"a": trashed.id, "b": unscanned.id}).all())
    assert states == {trashed.id: "pending", unscanned.id: "pending"}


def test_job_handles_every_tenant_with_its_own_dates(db):
    first, second = make_tenant(db, name="A"), make_tenant(db, name="B")
    photo_a = _photo(db, first.id, jpeg(taken_at=ORIGINAL))
    photo_b = _photo(db, second.id, jpeg(taken_at=ORIGINAL, color=(9, 9, 9)))
    _correct(db, _user(db, first), photo_a, day=date(2001, 1, 1), at=time(1, 0))
    _correct(db, _user(db, second), photo_b, day=date(2002, 2, 2), at=time(2, 0))

    assert capture_date_file_sync.process_pending(db)["written"] == 2
    db.refresh(photo_a)
    db.refresh(photo_b)
    assert _dto(_content(photo_a)) == "2001:01:01 01:00:00"
    assert _dto(_content(photo_b)) == "2002:02:02 02:00:00"
    assert photo_a.storage_path.startswith(f"uploads/tenant-{first.id}/") and photo_b.storage_path.startswith(f"uploads/tenant-{second.id}/")


def test_missing_object_marks_failed_and_reaches_the_error_log(db, monkeypatch):
    # Session.rollback() verwirft in der Test-Fixture das ganze Setup (äussere Transaktion); der
    # Fehler fällt vor jedem Schreiben, ein leeres Rollback genügt hier.
    monkeypatch.setattr(db, "rollback", lambda: None)
    errors: list[tuple[int | None, str]] = []
    monkeypatch.setattr(
        "app.core.error_log.record_system_error", lambda db_, exc, tenant_id=None, **kw: errors.append((tenant_id, type(exc).__name__))
    )
    tenant = make_tenant(db)
    user = _user(db, tenant)
    photo = _photo(db, tenant.id, jpeg(taken_at=ORIGINAL))
    _correct(db, user, photo)
    db.execute(text("UPDATE stored_file SET storage_path = :p WHERE id = :id"), {"p": f"uploads/fehlt-{uuid.uuid4().hex}.jpg", "id": photo.id})
    db.commit()

    assert capture_date_file_sync.process_pending(db)["failed"] == 1
    db.refresh(photo)
    assert photo.capture_file_state == "failed"
    assert errors == [(tenant.id, "ObjectNotFound")]
    # Eine neue Korrektur versucht es erneut.
    _correct(db, user, photo, day=date(2020, 1, 1))
    db.refresh(photo)
    assert photo.capture_file_state == "pending"


def test_job_is_registered_for_the_job_worker():
    from app.core.background_loops import BACKGROUND_LOCK_IDS
    from app.core.job_registry import JOB_DEFINITIONS
    from app.core.loops import JOB_WORKER_LOOPS, capture_date_file_sync_loop

    assert "capture_date_file_sync" in BACKGROUND_LOCK_IDS
    job = next(job for job in JOB_DEFINITIONS if job.name == "capture_date_file_sync")
    assert job.service == "job-worker" and job.interval_seconds == 60
    assert capture_date_file_sync_loop in JOB_WORKER_LOOPS


def test_pending_index_and_constraint_exist(db):
    assert db.execute(text("SELECT 1 FROM pg_indexes WHERE indexname = 'idx_stored_file_capture_file_pending'")).scalar() == 1
    tenant = make_tenant(db)
    photo = _photo(db, tenant.id, jpeg())
    with pytest.raises(Exception):
        with db.begin_nested():
            db.execute(text("UPDATE stored_file SET capture_file_state = 'bogus' WHERE id = :id"), {"id": photo.id})
    assert db.scalar(select(StoredFile.capture_file_state).where(StoredFile.id == photo.id)) is None
