"""Tests for the "Fotos" gallery upload window: extract_image_files_from_zip (only real
images survive a .zip, everything else is silently skipped), FileService.save_gallery_uploads
(magic-byte check, size cap, virus scan, tags, gallery_image row creation) and the
POST /files/gallery-uploads route end-to-end (multipart with a plain image and a .zip mixed
in one batch)."""
import asyncio
import io

import pytest
from fastapi import HTTPException, UploadFile
from PIL import Image
from starlette.datastructures import Headers

from app.api.routes import files as files_routes
from app.models.entities import GalleryImage, StoredFile
from app.services import file_service as file_service_module
from app.services.file_service import FileService, extract_image_files_from_zip
from tests.factories import make_current_user, make_tenant


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


def test_extract_image_files_from_zip_keeps_only_images_and_skips_junk():
    zip_bytes = _zip_of(
        {
            "urlaub/strand.png": _png_bytes((200, 100, 50)),
            "notizen.txt": b"kein Bild",
            "__MACOSX/._strand.png": b"junk",
        }
    )

    matched, notes = extract_image_files_from_zip(zip_bytes)

    matched_names = {name for name, _content in matched}
    assert matched_names == {"strand.png"}
    assert notes == []


def test_extract_image_files_from_zip_sniffs_content_not_filename():
    """Same security convention as the word-import ZIP extractor: an entry's real type is
    decided by its magic bytes, never its filename - a mislabeled ".jpg" whose actual bytes
    are a PNG is still recognized (and a non-image entry named ".png" would be rejected)."""
    zip_bytes = _zip_of({"urlaub/berg.jpg": _png_bytes((10, 10, 10))})

    matched, _notes = extract_image_files_from_zip(zip_bytes)

    assert {name for name, _content in matched} == {"berg.jpg"}


def test_extract_image_files_from_zip_reports_when_nothing_matches():
    zip_bytes = _zip_of({"bericht.docx": b"PK-artiges-aber-kein-bild", "readme.txt": b"hallo"})

    matched, notes = extract_image_files_from_zip(zip_bytes)

    assert matched == []
    assert notes == ["ZIP enthält keine Bilddateien"]


def test_save_gallery_uploads_stores_image_with_tags_and_creates_gallery_image_row(db):
    tenant = make_tenant(db)
    content = _png_bytes((30, 60, 90))

    items, errors = service.save_gallery_uploads(
        db, tenant_id=tenant.id, files=[("strand.png", content)], tags=["Sommerlager", " Sommerlager ", ""], created_by=None,
    )

    assert errors == []
    assert len(items) == 1
    item = items[0]
    assert item.source == "gallery_upload"
    assert item.tags == ["Sommerlager"]
    assert item.is_image is True

    stored_file = db.get(StoredFile, item.id)
    assert stored_file is not None
    assert stored_file.mime_type == "image/png"
    assert stored_file.scan_status in {"clean", "pending"}
    gallery_row = db.query(GalleryImage).filter_by(stored_file_id=stored_file.id).one_or_none()
    assert gallery_row is not None
    assert gallery_row.tenant_id == tenant.id


def test_save_gallery_uploads_rejects_non_image_content(db):
    tenant = make_tenant(db)

    items, errors = service.save_gallery_uploads(
        db, tenant_id=tenant.id, files=[("bericht.txt", b"das ist kein bild")], tags=[], created_by=None,
    )

    assert items == []
    assert len(errors) == 1
    assert "kein unterstütztes Bildformat" in errors[0]


def test_save_gallery_uploads_rejects_oversized_file(db, monkeypatch):
    tenant = make_tenant(db)
    monkeypatch.setattr(file_service_module, "MAX_UPLOAD_BYTES", 10)

    items, errors = service.save_gallery_uploads(
        db, tenant_id=tenant.id, files=[("strand.png", _png_bytes())], tags=[], created_by=None,
    )

    assert items == []
    assert "zu gross" in errors[0]


def test_save_gallery_uploads_rejects_infected_file_without_storing_it(db, monkeypatch):
    tenant = make_tenant(db)
    monkeypatch.setattr(file_service_module.scanner, "scan_bytes", lambda content, host, port: "infected")

    items, errors = service.save_gallery_uploads(
        db, tenant_id=tenant.id, files=[("strand.png", _png_bytes())], tags=[], created_by=None,
    )

    assert items == []
    assert len(errors) == 1
    assert "infiziert" in errors[0]
    assert db.query(StoredFile).filter_by(tenant_id=tenant.id).count() == 0


def test_save_gallery_uploads_does_not_abort_batch_on_one_bad_file(db):
    tenant = make_tenant(db)

    items, errors = service.save_gallery_uploads(
        db,
        tenant_id=tenant.id,
        files=[("gut.png", _png_bytes((1, 2, 3))), ("schlecht.txt", b"kein bild")],
        tags=["Lager"],
        created_by=None,
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
    tenant = make_tenant(db)
    writer = make_current_user(tenant.id, role="writer")
    zip_bytes = _zip_of({"a.png": _png_bytes((5, 5, 5)), "b.png": _png_bytes((250, 10, 10)), "notizen.txt": b"x"})

    result = asyncio.run(
        files_routes.upload_gallery_images(
            files=[
                _upload_file(_png_bytes((1, 1, 1)), "einzelbild.png", "image/png"),
                _upload_file(zip_bytes, "album.zip", "application/zip"),
            ],
            tags="Lager, Sommer",
            db=db,
            user=writer,
        )
    )

    assert len(result.items) == 3
    assert all(item.source == "gallery_upload" for item in result.items)
    assert all(item.tags == ["Lager", "Sommer"] for item in result.items)
    names = {item.original_name for item in result.items}
    assert names == {"einzelbild.png", "a.png", "b.png"}
