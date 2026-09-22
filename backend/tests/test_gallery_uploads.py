"""Tests for the "Fotos" gallery upload window: iter_gallery_zip_entries (only real images
survive a .zip, everything else is silently skipped), FileService.save_gallery_uploads
(magic-byte check, size cap, virus scan, tags, gallery_image row creation) and the
POST /files/gallery-uploads route end-to-end (stages a plain image and a .zip mixed in one
batch, queues a gallery_upload_job, then runs the background ingest loop's own task
synchronously to exercise the whole path in one test)."""
import asyncio
import io

import pytest
from fastapi import HTTPException, UploadFile
from PIL import Image
from starlette.datastructures import Headers

from datetime import date, datetime

from app.api.routes import files as files_routes
from app.core.cycle_utils import get_cycle_year
from app.models.entities import GalleryImage, GalleryUploadJob, PhotoAlbum, PhotoAlbumItem, StoredFile
from app.services import file_service as file_service_module
from app.services import public_id_service
from app.services.file_service import FileService
from app.services.upload_pipeline import iter_gallery_zip_entries
from tests.factories import make_current_user, make_cycle_config, make_event, make_tenant


@pytest.fixture(autouse=True)
def _isolated_storage_root(monkeypatch, tmp_path):
    # In the real running stack settings.storage_root is bind-mounted to the host's
    # ./storage directory - writing unmonkeypatched would leave real files behind on disk,
    # same convention as test_protocol_image_duplicate_check.py.
    from app.core.config import settings

    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(settings, "upload_root", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "thumbnail_root", str(tmp_path / "thumbnails"))


def _png_bytes(color=(10, 20, 30), size=(48, 48)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color=color).save(buffer, format="PNG")
    return buffer.getvalue()


def _jpeg_bytes_with_taken_at(taken_at: datetime, color=(10, 20, 30), size=(48, 48)) -> bytes:
    """A minimal JPEG carrying EXIF tag 306 (DateTime) - the plain fallback
    FileService._extract_image_metadata reads when the more specific DateTimeOriginal/
    DigitizedDateTime sub-IFD tags aren't present, simplest to write via PIL's Exif dict."""
    buffer = io.BytesIO()
    exif = Image.Exif()
    exif[306] = taken_at.strftime("%Y:%m:%d %H:%M:%S")
    Image.new("RGB", size, color=color).save(buffer, format="JPEG", exif=exif)
    return buffer.getvalue()


def _zip_of(entries: dict[str, bytes]) -> bytes:
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def _upload_file(content: bytes, filename: str, content_type: str = "application/octet-stream") -> UploadFile:
    return UploadFile(file=io.BytesIO(content), filename=filename, headers=Headers({"content-type": content_type}))


service = FileService()


def _drain_zip_entries(zip_bytes: bytes, tmp_path) -> tuple[list[tuple[str, bytes]], list[str]]:
    """iter_gallery_zip_entries streams matches/notes off a ZIP staged on disk instead of
    returning them as one (matched, notes) pair - this collects a generator's output into
    that same shape so the tests below can assert on it the same way."""
    zip_path = tmp_path / "upload.zip"
    zip_path.write_bytes(zip_bytes)
    matched: list[tuple[str, bytes]] = []
    notes: list[str] = []
    for item in iter_gallery_zip_entries(zip_path):
        (notes if isinstance(item, str) else matched).append(item)
    return matched, notes


def test_iter_gallery_zip_entries_keeps_only_images_and_skips_junk(tmp_path):
    zip_bytes = _zip_of(
        {
            "urlaub/strand.png": _png_bytes((200, 100, 50)),
            "notizen.txt": b"kein Bild",
            "__MACOSX/._strand.png": b"junk",
        }
    )

    matched, notes = _drain_zip_entries(zip_bytes, tmp_path)

    matched_names = {name for name, _content in matched}
    assert matched_names == {"strand.png"}
    assert notes == []


def test_iter_gallery_zip_entries_sniffs_content_not_filename(tmp_path):
    """Same security convention as the word-import ZIP extractor: an entry's real type is
    decided by its magic bytes, never its filename - a mislabeled ".jpg" whose actual bytes
    are a PNG is still recognized (and a non-image entry named ".png" would be rejected)."""
    zip_bytes = _zip_of({"urlaub/berg.jpg": _png_bytes((10, 10, 10))})

    matched, _notes = _drain_zip_entries(zip_bytes, tmp_path)

    assert {name for name, _content in matched} == {"berg.jpg"}


def test_iter_gallery_zip_entries_reports_nothing_for_a_zip_with_no_images(tmp_path):
    zip_bytes = _zip_of({"bericht.docx": b"PK-artiges-aber-kein-bild", "readme.txt": b"hallo"})

    matched, notes = _drain_zip_entries(zip_bytes, tmp_path)

    # Unlike the old in-memory extract_image_files_from_zip, the streaming generator
    # doesn't synthesize a friendly "ZIP enthält keine Bilddateien" note itself (it has no
    # way to know "nothing matched" until fully drained) - FileService._ingest_gallery_zip's
    # own saw_anything check is what surfaces that message to the user instead (see
    # test_gallery_upload_job_reports_a_zip_with_no_images below).
    assert matched == []
    assert notes == []


def test_save_gallery_uploads_stores_image_with_tags_and_creates_gallery_image_row(db):
    tenant = make_tenant(db)
    content = _png_bytes((30, 60, 90))

    items, errors = asyncio.run(
        service.save_gallery_uploads(
            db, tenant_id=tenant.id, files=[("strand.png", content)], tags=["Sommerlager", " Sommerlager ", ""], created_by=None,
        )
    )

    assert errors == []
    assert len(items) == 1
    item = items[0]
    assert item.source == "gallery_upload"
    assert item.tags == ["Sommerlager"]
    assert item.is_image is True

    stored_file = public_id_service.get_by_public_id(db, StoredFile, item.id)
    assert stored_file is not None
    assert stored_file.mime_type == "image/png"
    assert stored_file.scan_status in {"clean", "pending"}
    gallery_row = db.query(GalleryImage).filter_by(stored_file_id=stored_file.id).one_or_none()
    assert gallery_row is not None
    assert gallery_row.tenant_id == tenant.id


def test_save_gallery_uploads_persists_exif_taken_at_and_uses_it_as_group_date(db):
    tenant = make_tenant(db)
    content = _jpeg_bytes_with_taken_at(datetime(2026, 3, 4, 12, 0))

    items, errors = asyncio.run(
        service.save_gallery_uploads(db, tenant_id=tenant.id, files=[("bild.jpg", content)], tags=[], created_by=None)
    )

    assert errors == []
    stored_file = public_id_service.get_by_public_id(db, StoredFile, items[0].id)
    assert stored_file.exif_taken_at is not None
    assert stored_file.exif_taken_at.date() == date(2026, 3, 4)
    assert items[0].group_date == date(2026, 3, 4)


def test_save_gallery_uploads_auto_links_a_photo_to_the_termin_on_its_capture_date(db):
    """The Termin -> Bild direction of the auto-link feature: uploading without an
    explicit Termin target still links the photo when its EXIF capture date falls inside
    an existing (possibly multi-day) Termin's range."""
    tenant = make_tenant(db)
    event = make_event(db, tenant.id, title="Sommerlager", event_date=date(2026, 7, 10), event_end_date=date(2026, 7, 13))
    content = _jpeg_bytes_with_taken_at(datetime(2026, 7, 12, 15, 0))

    items, errors = asyncio.run(
        service.save_gallery_uploads(db, tenant_id=tenant.id, files=[("lager.jpg", content)], tags=[], created_by=None)
    )

    assert errors == []
    stored_file = public_id_service.get_by_public_id(db, StoredFile, items[0].id)
    gallery_row = db.query(GalleryImage).filter_by(stored_file_id=stored_file.id).one()
    assert gallery_row.event_id == event.id
    assert gallery_row.event_auto_linked is True
    assert items[0].context_label == "Sommerlager"
    assert items[0].ref_date == event.event_date
    assert items[0].ref_end_date == event.event_end_date


def test_save_gallery_uploads_does_not_auto_link_when_capture_date_matches_no_termin(db):
    tenant = make_tenant(db)
    make_event(db, tenant.id, title="Sommerlager", event_date=date(2026, 7, 10), event_end_date=date(2026, 7, 13))
    content = _jpeg_bytes_with_taken_at(datetime(2026, 9, 1, 15, 0))

    items, errors = asyncio.run(
        service.save_gallery_uploads(db, tenant_id=tenant.id, files=[("herbst.jpg", content)], tags=[], created_by=None)
    )

    assert errors == []
    stored_file = public_id_service.get_by_public_id(db, StoredFile, items[0].id)
    gallery_row = db.query(GalleryImage).filter_by(stored_file_id=stored_file.id).one()
    assert gallery_row.event_id is None
    assert gallery_row.event_auto_linked is False


def test_save_gallery_uploads_with_an_explicit_event_target_is_not_marked_auto_linked(db):
    """A manually picked Termin (GalleryUploadModal's picker) must win over date matching
    and never be flagged as if photo_event_link_service had auto-matched it - otherwise a
    later Termin date edit could unlink this deliberate choice."""
    tenant = make_tenant(db)
    picked_event = make_event(db, tenant.id, title="Elternabend", event_date=date(2026, 1, 1))
    # EXIF date deliberately doesn't match picked_event's date at all.
    content = _jpeg_bytes_with_taken_at(datetime(2026, 7, 12, 15, 0))

    items, errors = asyncio.run(
        service.save_gallery_uploads(
            db, tenant_id=tenant.id, files=[("bild.jpg", content)], tags=[], created_by=None,
            upload_event_id=picked_event.id,
        )
    )

    assert errors == []
    stored_file = public_id_service.get_by_public_id(db, StoredFile, items[0].id)
    gallery_row = db.query(GalleryImage).filter_by(stored_file_id=stored_file.id).one()
    assert gallery_row.event_id == picked_event.id
    assert gallery_row.event_auto_linked is False


def test_save_gallery_uploads_with_a_cycle_config_target_files_photos_into_the_cycle_album(db):
    """Regression coverage (audit fix, 2026-09-17): the cycle_config upload target used to
    hand-roll get_or_create_cycle_album/add_items/commit/recompute_best_of inline instead
    of routing through photo_album_service.assign_uploaded_files' (previously dead)
    cycle_config/fallback_date branch - this exercises that path end-to-end rather than
    just unit-testing the two pieces in isolation."""
    tenant = make_tenant(db)
    cycle_config = make_cycle_config(db, tenant.id, name="Biber", reset_month=12, reset_day=31)
    content = _png_bytes((5, 15, 25))

    items, errors = asyncio.run(
        service.save_gallery_uploads(
            db, tenant_id=tenant.id, files=[("lager.png", content)], tags=[], created_by=None,
            upload_cycle_config=cycle_config,
        )
    )

    assert errors == []
    assert len(items) == 1
    stored_file = public_id_service.get_by_public_id(db, StoredFile, items[0].id)

    expected_cycle_year = get_cycle_year(date.today(), cycle_config.reset_month, cycle_config.reset_day)
    album = db.query(PhotoAlbum).filter_by(tenant_id=tenant.id, kind="cycle", cycle_config_id=cycle_config.id, cycle_year=expected_cycle_year).one()
    item_row = db.query(PhotoAlbumItem).filter_by(album_id=album.id, file_id=stored_file.public_id).one_or_none()
    assert item_row is not None


def test_save_gallery_uploads_flags_a_duplicate_within_the_same_batch(db):
    """Regression coverage (audit fix, 2026-09-17): ingest_file's tenant_hashes batching
    appends each newly-hashed file to the shared list save_gallery_uploads passes in, so a
    near-duplicate pair uploaded together in one ZIP/batch is still caught against each
    other, not just against files that already existed before this batch started. A
    flat-color image is a degenerate case for perceptual hashing - two of them (even
    different colors) hash near-identically, which is exactly what's wanted here: two
    files with no pre-existing tenant history, similar only to each other."""
    tenant = make_tenant(db)
    first = _png_bytes((10, 10, 10))
    second = _png_bytes((12, 12, 12))

    items, errors = asyncio.run(
        service.save_gallery_uploads(
            db, tenant_id=tenant.id, files=[("a.png", first), ("b.png", second)], tags=[], created_by=None,
        )
    )

    assert len(items) == 2
    assert any("ähnelt einem bereits im Mandanten hochgeladenen Bild" in error for error in errors)


def test_save_gallery_uploads_rejects_non_image_content(db):
    tenant = make_tenant(db)

    items, errors = asyncio.run(
        service.save_gallery_uploads(
            db, tenant_id=tenant.id, files=[("bericht.txt", b"das ist kein bild")], tags=[], created_by=None,
        )
    )

    assert items == []
    assert len(errors) == 1
    assert "kein unterstütztes Bildformat" in errors[0]


def test_save_gallery_uploads_rejects_oversized_file(db, monkeypatch):
    tenant = make_tenant(db)
    monkeypatch.setattr(file_service_module, "MAX_UPLOAD_BYTES", 10)

    items, errors = asyncio.run(
        service.save_gallery_uploads(
            db, tenant_id=tenant.id, files=[("strand.png", _png_bytes())], tags=[], created_by=None,
        )
    )

    assert items == []
    assert "zu gross" in errors[0]


def test_save_gallery_uploads_rejects_infected_file_without_storing_it(db, monkeypatch):
    tenant = make_tenant(db)
    monkeypatch.setattr(file_service_module.scanner, "scan_bytes", lambda content, host, port: "infected")

    items, errors = asyncio.run(
        service.save_gallery_uploads(
            db, tenant_id=tenant.id, files=[("strand.png", _png_bytes())], tags=[], created_by=None,
        )
    )

    assert items == []
    assert len(errors) == 1
    assert "infiziert" in errors[0]
    assert db.query(StoredFile).filter_by(tenant_id=tenant.id).count() == 0


def test_save_gallery_uploads_does_not_abort_batch_on_one_bad_file(db):
    tenant = make_tenant(db)

    items, errors = asyncio.run(
        service.save_gallery_uploads(
            db,
            tenant_id=tenant.id,
            files=[("gut.png", _png_bytes((1, 2, 3))), ("schlecht.txt", b"kein bild")],
            tags=["Lager"],
            created_by=None,
        )
    )

    assert len(items) == 1
    assert items[0].original_name == "gut.png"
    assert len(errors) == 1


def test_upload_gallery_images_route_requires_writer_role(db):
    tenant = make_tenant(db)
    reader = make_current_user(tenant.id, role="reader")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            files_routes.upload_gallery_images(
                files=[_upload_file(_png_bytes(), "strand.png", "image/png")], tags="Lager", db=db, user=reader,
            )
        )
    assert exc_info.value.status_code == 403


def test_upload_gallery_images_route_accepts_mixed_batch_of_image_and_zip(db):
    """The route now only stages the upload(s) to disk and queues a gallery_upload_job
    (status "queued", total_files None since a ZIP is in the batch - see
    upload_gallery_images) instead of ingesting inline - process_pending_gallery_upload_jobs
    (the background loop's own task) is what actually scans/stores everything, run here
    synchronously to exercise the whole path in one test."""
    tenant = make_tenant(db)
    writer = make_current_user(tenant.id, role="writer")
    zip_bytes = _zip_of({"a.png": _png_bytes((5, 5, 5)), "b.png": _png_bytes((250, 10, 10)), "notizen.txt": b"x"})

    queued = asyncio.run(
        files_routes.upload_gallery_images(
            files=[
                _upload_file(_png_bytes((1, 1, 1)), "einzelbild.png", "image/png"),
                _upload_file(zip_bytes, "album.zip", "application/zip"),
            ],
            tags="Lager, Sommer",
            event_id=None,
            submission_assignment_id=None,
            submission_element_ref=None,
            cycle_config_id=None,
            db=db,
            user=writer,
        )
    )
    assert queued.status == "queued"
    assert queued.total_files is None  # unknown upfront - the ZIP hasn't been opened yet
    job = db.get(GalleryUploadJob, queued.id)
    assert job is not None
    assert len(job.staged_paths) == 2

    service.process_pending_gallery_upload_jobs(db)

    db.refresh(job)
    assert job.status == "done"
    assert job.total_files == 3
    assert job.processed_files == 3
    assert len(job.imported_file_ids) == 3
    # Any two flat-color PNGs phash near-identically regardless of the actual color (a DCT
    # of a uniform image has no frequency content past the DC term) - _png_bytes' fixtures
    # trip the perceptual-duplicate hint against each other for that reason. That's an
    # informational note, not a failure (all 3 still imported, asserted above) - only
    # assert there's no real failure (too-large/unsupported-format/infected) message.
    assert all("ähnelt" in error for error in job.errors)

    detail = files_routes.get_gallery_upload_job(queued.id, db=db, user=writer)
    assert all(item.source == "gallery_upload" for item in detail.imported_items)
    assert all(item.tags == ["Lager", "Sommer"] for item in detail.imported_items)
    names = {item.original_name for item in detail.imported_items}
    assert names == {"einzelbild.png", "a.png", "b.png"}


def test_gallery_upload_job_reports_a_zip_with_no_images(db):
    tenant = make_tenant(db)
    writer = make_current_user(tenant.id, role="writer")
    zip_bytes = _zip_of({"bericht.docx": b"PK-artiges-aber-kein-bild", "readme.txt": b"hallo"})

    queued = asyncio.run(
        files_routes.upload_gallery_images(
            files=[_upload_file(zip_bytes, "leer.zip", "application/zip")],
            tags=None,
            event_id=None,
            submission_assignment_id=None,
            submission_element_ref=None,
            cycle_config_id=None,
            db=db,
            user=writer,
        )
    )
    service.process_pending_gallery_upload_jobs(db)

    job = db.get(GalleryUploadJob, queued.id)
    assert job.status == "done"
    assert job.imported_file_ids == []
    assert job.errors == ["ZIP enthält keine Bilddateien"]
