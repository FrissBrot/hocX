"""HEIC/HEIF und Live Photos in der Galerie (apple_media.py): Erkennung und Umwandlung nach JPEG,
Zuordnung von Clip und Bild ueber den Dateinamen (direkt und im ZIP), Speichern des Clips als
eigener stored_file, Auslieferung als live_video_url und Loeschen zusammen mit dem Bild.

HEIC-Fixtures entstehen mit pillow-heif selbst, der Live-Clip mit dem echten ffmpeg (HEVC im
MOV-Container wie beim iPhone) - Tests, die ffmpeg brauchen, werden ohne es uebersprungen."""
import asyncio
import io
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest
from fastapi import HTTPException, UploadFile
from PIL import Image
from starlette.datastructures import Headers

from app.api.routes import files as files_routes
from app.core.config import settings
from app.models.entities import GalleryImage, GalleryUploadJob, StoredFile
from app.services import apple_media, file_service as file_service_module, public_id_service
from app.services.file_service import FileService
from app.services.upload_pipeline import GalleryZipClip, _sniff_image_mime, iter_gallery_zip_entries
from tests.factories import make_current_user, make_tenant

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg nicht installiert")

service = FileService()


@pytest.fixture(autouse=True)
def _isolated_storage_root(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(settings, "upload_root", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "thumbnail_root", str(tmp_path / "thumbnails"))


def _heic_bytes(size=(64, 48), color=(200, 40, 40), orientation: int | None = None, taken_at: str | None = None) -> bytes:
    image = Image.new("RGB", size, color=color)
    exif = Image.Exif()
    if orientation is not None:
        exif[274] = orientation
    if taken_at is not None:
        exif[306] = taken_at
    buffer = io.BytesIO()
    image.save(buffer, format="HEIF", exif=exif.tobytes() if len(exif) else None)
    return buffer.getvalue()


def _mov_bytes(seconds: int = 1) -> bytes:
    """Kleiner HEVC-Clip im QuickTime-Container, so wie ihn ein iPhone fuer Live Photos schreibt."""
    result = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc=size=320x240:rate=15:duration={seconds}",
            "-c:v", "libx265", "-pix_fmt", "yuv420p", "-tag:v", "hvc1", "-f", "mov", "-movflags", "frag_keyframe+empty_moov", "pipe:1",
        ],
        capture_output=True,
        check=True,
    )
    return result.stdout


def _png_bytes(color=(10, 20, 30), size=(48, 48)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color=color).save(buffer, format="PNG")
    return buffer.getvalue()


def _zip_of(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def _upload_file(content: bytes, filename: str) -> UploadFile:
    return UploadFile(file=io.BytesIO(content), filename=filename, headers=Headers({"content-type": "application/octet-stream"}))


# --- Erkennung und Umwandlung -------------------------------------------------------------


def test_is_heic_recognizes_the_ftyp_brand_and_nothing_else():
    assert apple_media.is_heic(_heic_bytes())
    assert not apple_media.is_heic(_png_bytes())
    assert not apple_media.is_heic(b"\x00\x00\x00\x18ftypqt  " + b"\x00" * 8)  # QuickTime, kein HEIC
    assert not apple_media.is_heic(b"")


def test_gallery_sniff_accepts_heic_but_protocol_images_do_not():
    from app.services.upload_pipeline import ALLOWED_IMAGE_MIME_TYPES

    assert _sniff_image_mime(_heic_bytes()) == "image/heic"
    assert "image/heic" not in ALLOWED_IMAGE_MIME_TYPES


def test_convert_heic_to_jpeg_keeps_pixels_and_exif_date():
    jpeg = apple_media.convert_heic_to_jpeg(_heic_bytes(size=(64, 48), taken_at="2026:07:14 09:30:00"))

    assert jpeg is not None and jpeg.startswith(b"\xff\xd8\xff")
    with Image.open(io.BytesIO(jpeg)) as image:
        assert image.size == (64, 48)
        assert image.getexif().get(306) == "2026:07:14 09:30:00"


def test_convert_heic_to_jpeg_applies_the_camera_rotation():
    # Hochkant-Foto: Sensor liefert 64x48 quer, EXIF-Orientierung 6 dreht es auf 48x64.
    jpeg = apple_media.convert_heic_to_jpeg(_heic_bytes(size=(64, 48), orientation=6))

    with Image.open(io.BytesIO(jpeg)) as image:
        assert image.size == (48, 64)
        assert image.getexif().get(274) in (None, 1)  # nicht noch einmal drehen


def test_convert_heic_to_jpeg_returns_none_for_a_truncated_file():
    assert apple_media.convert_heic_to_jpeg(_heic_bytes()[:40]) is None


def test_jpeg_filename_replaces_the_extension():
    assert apple_media.jpeg_filename("IMG_1234.HEIC") == "IMG_1234.jpg"
    assert apple_media.jpeg_filename("ohne-endung") == "ohne-endung.jpg"


# --- Zuordnung Bild <-> Clip --------------------------------------------------------------


def test_pair_live_clips_matches_by_name_case_insensitively():
    names = ["IMG_1.HEIC", "img_1.mov", "IMG_2.JPG", "IMG_3.HEIC", "IMG_3.MP4"]

    assert apple_media.pair_live_clips(names) == {0: 1, 3: 4}


def test_pair_live_clips_does_not_reuse_a_clip_and_leaves_orphans_out():
    names = ["a.heic", "a.jpg", "a.mov", "lonely.mov", "sub/b.heic", "b.mov"]

    # a.mov gehoert nur zum ersten Bild; b.mov liegt in einem anderen Ordner als sub/b.heic.
    assert apple_media.pair_live_clips(names) == {0: 2}


def test_pair_live_clips_pairs_within_the_same_folder():
    assert apple_media.pair_live_clips(["Urlaub/IMG_1.HEIC", "Urlaub/IMG_1.MOV"]) == {0: 1}


# --- ZIP ----------------------------------------------------------------------------------


def test_zip_yields_the_clip_right_after_its_image_and_skips_orphan_clips(tmp_path):
    zip_path = tmp_path / "export.zip"
    zip_path.write_bytes(
        _zip_of(
            {
                "IMG_1.MOV": b"\x00\x00\x00\x14ftypqt  " + b"\x00" * 32,
                "IMG_1.HEIC": _heic_bytes(),
                "ohne-bild.MOV": b"\x00\x00\x00\x14ftypqt  " + b"\x00" * 32,
            }
        )
    )

    items = list(iter_gallery_zip_entries(zip_path))

    assert [type(item) for item in items] == [tuple, GalleryZipClip]
    assert items[0][0] == "IMG_1.HEIC"
    assert items[1].image_name == "IMG_1.HEIC"


# --- Speichern ----------------------------------------------------------------------------


def test_save_gallery_uploads_converts_heic_to_a_jpeg_photo(db):
    tenant = make_tenant(db)

    items, errors = asyncio.run(
        service.save_gallery_uploads(
            db, tenant_id=tenant.id, files=[("IMG_0001.HEIC", _heic_bytes(size=(80, 60)))], tags=[], created_by=None
        )
    )

    assert errors == []
    assert [item.original_name for item in items] == ["IMG_0001.jpg"]
    stored = public_id_service.get_by_public_id(db, StoredFile, items[0].id)
    assert stored.mime_type == "image/jpeg"
    assert (stored.width, stored.height) == (80, 60)
    assert stored.thumbnail_path is not None
    assert items[0].live_video_url is None


def test_save_gallery_uploads_reports_an_unreadable_heic_and_keeps_the_rest(db):
    tenant = make_tenant(db)

    items, errors = asyncio.run(
        service.save_gallery_uploads(
            db,
            tenant_id=tenant.id,
            files=[("kaputt.heic", _heic_bytes()[:40]), ("gut.png", _png_bytes())],
            tags=[],
            created_by=None,
        )
    )

    assert [item.original_name for item in items] == ["gut.png"]
    assert errors == ["kaputt.heic: HEIC-Datei konnte nicht gelesen werden"]


def test_infected_heic_is_rejected_without_being_decoded(db, monkeypatch):
    tenant = make_tenant(db)
    monkeypatch.setattr(file_service_module.scanner, "scan_bytes", lambda content, host, port: "infected")
    monkeypatch.setattr(
        file_service_module, "convert_heic_to_jpeg", lambda content: pytest.fail("infizierte Datei darf nicht dekodiert werden")
    )

    items, errors = asyncio.run(
        service.save_gallery_uploads(db, tenant_id=tenant.id, files=[("x.heic", _heic_bytes())], tags=[], created_by=None)
    )

    assert items == []
    assert "infiziert" in errors[0]
    assert db.query(StoredFile).filter_by(tenant_id=tenant.id).count() == 0


@needs_ffmpeg
def test_live_photo_is_stored_as_photo_plus_playable_mp4(db):
    tenant = make_tenant(db)
    clip = _mov_bytes()

    items, errors = asyncio.run(
        service.save_gallery_uploads(
            db,
            tenant_id=tenant.id,
            files=[("IMG_0002.HEIC", _heic_bytes())],
            tags=[],
            created_by=None,
            live_clips={"IMG_0002.HEIC": clip},
        )
    )

    assert errors == []
    assert len(items) == 1
    assert items[0].live_video_url is not None
    gallery_row = db.query(GalleryImage).filter_by(tenant_id=tenant.id).one()
    video = db.get(StoredFile, gallery_row.live_video_stored_file_id)
    assert video.mime_type == "video/mp4"
    assert video.original_name == "IMG_0002.mp4"
    assert items[0].live_video_url == f"/api/stored-files/{video.public_id}/content"
    # H.264 (nicht mehr HEVC) im MP4-Container, ohne Ton.
    written = (Path(settings.storage_root) / video.storage_path).read_bytes()
    assert written[4:8] == b"ftyp"
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,codec_type", "-of", "csv=p=0", "-"],
        input=written,
        capture_output=True,
        check=True,
    ).stdout.decode()
    assert "h264,video" in probe
    assert "audio" not in probe
    assert video.storage_path.endswith(".mp4")


@needs_ffmpeg
def test_live_clip_does_not_show_up_as_a_gallery_item_of_its_own(db):
    tenant = make_tenant(db)
    asyncio.run(
        service.save_gallery_uploads(
            db,
            tenant_id=tenant.id,
            files=[("IMG_0003.HEIC", _heic_bytes())],
            tags=[],
            created_by=None,
            live_clips={"IMG_0003.HEIC": _mov_bytes()},
        )
    )

    rows = service.list_tenant_files(db, tenant.id, limit=50)

    assert len(rows) == 1
    assert rows[0].original_name == "IMG_0003.jpg"
    assert rows[0].live_video_url is not None
    # Der Clip zaehlt aber zum Speicher des Mandanten.
    assert db.query(StoredFile).filter_by(tenant_id=tenant.id).count() == 2


def test_an_unusable_live_clip_leaves_a_plain_photo_and_a_note(db):
    tenant = make_tenant(db)

    items, errors = asyncio.run(
        service.save_gallery_uploads(
            db,
            tenant_id=tenant.id,
            files=[("IMG_0004.HEIC", _heic_bytes())],
            tags=[],
            created_by=None,
            live_clips={"IMG_0004.HEIC": b"\x00\x00\x00\x14ftypqt  " + b"kein echtes video"},
        )
    )

    assert len(items) == 1
    assert items[0].live_video_url is None
    assert errors == ["IMG_0004.HEIC: Live-Photo-Video konnte nicht verarbeitet werden, als normales Foto gespeichert"]
    assert db.query(StoredFile).filter_by(tenant_id=tenant.id).count() == 1


def test_infected_live_clip_is_not_stored_but_the_photo_is(db, monkeypatch):
    tenant = make_tenant(db)
    infected_clip = b"\x00\x00\x00\x14ftypqt  " + b"EICAR"
    monkeypatch.setattr(
        file_service_module.scanner, "scan_bytes", lambda content, host, port: "infected" if content == infected_clip else "clean"
    )

    items, errors = asyncio.run(
        service.save_gallery_uploads(
            db,
            tenant_id=tenant.id,
            files=[("IMG_0005.HEIC", _heic_bytes())],
            tags=[],
            created_by=None,
            live_clips={"IMG_0005.HEIC": infected_clip},
        )
    )

    assert len(items) == 1 and items[0].live_video_url is None
    assert "infiziert" in errors[0]


@needs_ffmpeg
def test_deleting_the_photo_deletes_its_live_clip(db):
    tenant = make_tenant(db)
    items, _ = asyncio.run(
        service.save_gallery_uploads(
            db,
            tenant_id=tenant.id,
            files=[("IMG_0006.HEIC", _heic_bytes())],
            tags=[],
            created_by=None,
            live_clips={"IMG_0006.HEIC": _mov_bytes()},
        )
    )

    deleted, errors = service.delete_gallery_images(db, tenant.id, [items[0].id])
    db.commit()

    assert deleted == [items[0].id] and errors == []
    assert db.query(StoredFile).filter_by(tenant_id=tenant.id).count() == 0


# --- Upload-Route und Hintergrund-Job -----------------------------------------------------


@needs_ffmpeg
def test_route_pairs_separately_uploaded_heic_and_mov(db):
    tenant = make_tenant(db)
    writer = make_current_user(tenant.id, role="writer")

    queued = asyncio.run(
        files_routes.upload_gallery_images(
            files=[
                _upload_file(_mov_bytes(), "IMG_0007.MOV"),
                _upload_file(_heic_bytes(), "IMG_0007.HEIC"),
                _upload_file(_png_bytes((9, 9, 9)), "daneben.png"),
            ],
            tags=None,
            event_id=None,
            submission_assignment_id=None,
            submission_element_ref=None,
            cycle_config_id=None,
            db=db,
            user=writer,
        )
    )
    # Der Clip ist kein eigenes Foto: nicht in der Gesamtzahl des Fortschrittsbalkens.
    assert queued.total_files == 2

    service.process_pending_gallery_upload_jobs(db)

    job = db.get(GalleryUploadJob, queued.id)
    assert job.status == "done"
    assert job.processed_files == 2
    assert len(job.imported_file_ids) == 2
    detail = files_routes.get_gallery_upload_job(queued.id, db=db, user=writer)
    by_name = {item.original_name: item for item in detail.imported_items}
    assert set(by_name) == {"IMG_0007.jpg", "daneben.png"}
    assert by_name["IMG_0007.jpg"].live_video_url is not None
    assert by_name["daneben.png"].live_video_url is None
    # Alle gestagten Dateien (auch der Clip) sind wieder aufgeraeumt.
    assert list((Path(settings.upload_root) / "_staging" / "gallery").glob("*")) == []


@needs_ffmpeg
def test_zip_with_live_photos_keeps_pairs_together_across_batches(db, monkeypatch):
    tenant = make_tenant(db)
    writer = make_current_user(tenant.id, role="writer")
    monkeypatch.setattr(FileService, "GALLERY_INGEST_BATCH_SIZE", 2)
    clip = _mov_bytes()
    entries = {}
    for number in range(1, 4):
        entries[f"IMG_{number}.HEIC"] = _heic_bytes(color=(number * 40, 10, 10))
        entries[f"IMG_{number}.MOV"] = clip

    queued = asyncio.run(
        files_routes.upload_gallery_images(
            files=[_upload_file(_zip_of(entries), "export.zip")],
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
    assert job.total_files == 3 and job.processed_files == 3
    detail = files_routes.get_gallery_upload_job(queued.id, db=db, user=writer)
    assert len(detail.imported_items) == 3
    assert all(item.live_video_url is not None for item in detail.imported_items)


@needs_ffmpeg
def test_live_clip_is_served_inline_as_video_mp4(db, monkeypatch):
    """Das <video src> der Galerie holt den Clip ueber denselben Content-Endpoint wie Bilder -
    er muss als video/mp4 inline ausgeliefert werden (Range-Anfragen bedient FileResponse selbst)."""
    tenant = make_tenant(db)
    writer = make_current_user(tenant.id, role="writer")
    monkeypatch.setattr(file_service_module.scanner, "scan_bytes", lambda content, host, port: "clean")
    items, _ = asyncio.run(
        service.save_gallery_uploads(
            db,
            tenant_id=tenant.id,
            files=[("IMG_0008.HEIC", _heic_bytes())],
            tags=[],
            created_by=None,
            live_clips={"IMG_0008.HEIC": _mov_bytes()},
        )
    )
    clip_public_id = items[0].live_video_url.split("/")[-2]

    response = files_routes.get_stored_file_content(clip_public_id, db=db, user=writer)

    assert response.media_type == "video/mp4"
    assert response.headers["content-disposition"].startswith("inline")
    assert response.headers["x-content-type-options"] == "nosniff"


def _save_live_photo(db, tenant, monkeypatch, name="IMG_0009.HEIC"):
    monkeypatch.setattr(file_service_module.scanner, "scan_bytes", lambda content, host, port: "clean")
    items, _ = asyncio.run(
        service.save_gallery_uploads(
            db, tenant_id=tenant.id, files=[(name, _heic_bytes())], tags=[], created_by=None, live_clips={name: _mov_bytes()}
        )
    )
    return items[0].id


@needs_ffmpeg
def test_download_lets_the_user_pick_image_video_or_both(db, monkeypatch):
    tenant = make_tenant(db)
    writer = make_current_user(tenant.id, role="writer")
    photo_id = _save_live_photo(db, tenant, monkeypatch)

    image = files_routes.download_stored_file(photo_id, part="image", db=db, user=writer)
    assert image.media_type == "image/jpeg"
    assert image.headers["content-disposition"].startswith("attachment")
    assert "IMG_0009.jpg" in image.headers["content-disposition"]

    video = files_routes.download_stored_file(photo_id, part="video", db=db, user=writer)
    assert video.media_type == "video/mp4"
    assert video.headers["content-disposition"].startswith("attachment")
    assert "IMG_0009.mp4" in video.headers["content-disposition"]

    both = files_routes.download_stored_file(photo_id, part="both", db=db, user=writer)
    assert both.media_type == "application/zip"
    with zipfile.ZipFile(both.path) as archive:
        # Gleicher Name, nur andere Endung: so laesst sich das Paar wieder als Live Photo hochladen.
        assert sorted(archive.namelist()) == ["IMG_0009.jpg", "IMG_0009.mp4"]
        assert archive.read("IMG_0009.jpg").startswith(b"\xff\xd8\xff")
        assert archive.read("IMG_0009.mp4")[4:8] == b"ftyp"
    asyncio.run(both.background())
    assert not Path(both.path).exists()


def test_download_of_an_ordinary_photo_has_no_video(db, monkeypatch):
    tenant = make_tenant(db)
    writer = make_current_user(tenant.id, role="writer")
    monkeypatch.setattr(file_service_module.scanner, "scan_bytes", lambda content, host, port: "clean")
    items, _ = asyncio.run(
        service.save_gallery_uploads(db, tenant_id=tenant.id, files=[("a.png", _png_bytes())], tags=[], created_by=None)
    )

    with pytest.raises(HTTPException) as exc_info:
        files_routes.download_stored_file(items[0].id, part="video", db=db, user=writer)
    assert exc_info.value.status_code == 404
    # "both" degrades to the plain image instead of a ZIP with one file.
    both = files_routes.download_stored_file(items[0].id, part="both", db=db, user=writer)
    assert both.media_type == "image/png"


@needs_ffmpeg
def test_download_is_refused_for_other_tenants(db, monkeypatch):
    tenant = make_tenant(db)
    other = make_tenant(db, "Anderer Mandant")
    photo_id = _save_live_photo(db, tenant, monkeypatch)

    with pytest.raises(HTTPException) as exc_info:
        files_routes.download_stored_file(photo_id, part="video", db=db, user=make_current_user(other.id, role="writer"))
    assert exc_info.value.status_code == 403
