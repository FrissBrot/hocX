"""Nachtlauf 2026-11-25 (Verdacht zu #147): abgeschnittene PNG/WebP/HEIC im Metadatenfilter und
ein Album-ZIP, das an einem einzelnen nicht filterbaren Bild nicht mehr komplett scheitert."""

import asyncio
import io
import struct
import zipfile
import zlib

import pytest
from fastapi import HTTPException
from PIL import Image
from sqlalchemy import select

from app.api.routes import public_share as public_share_routes
from app.api.routes import share_links as share_links_routes
from app.models.entities import StoredFile
from app.schemas.files import ShareLinkCreate
from app.services.file_service import FileService
from app.services.photo_metadata_privacy import ImageSanitizeError, MetadataPolicy, sanitize_image
from tests.factories import make_current_user, make_tenant
from tests.image_fixtures import jpeg, response_bytes
from tests.test_public_share_truncated_jpeg import _FakeRequest, _isolated_storage_root  # noqa: F401 (Fixture)

WITHOUT_LOCATION = MetadataPolicy(location=False, capture_date=True, camera=False)


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)


def _png_with_text() -> bytes:
    buffer = io.BytesIO()
    Image.frombytes("RGB", (64, 48), bytes((i * 7) % 256 for i in range(64 * 48 * 3))).save(buffer, format="PNG")
    full = buffer.getvalue()
    ihdr_end = 8 + 25
    # Textchunk mit Standort vor den Bilddaten (wie «Raw profile type exif»/XMP)
    return full[:ihdr_end] + _chunk(b"tEXt", b"Comment\x00GPS 47.37 8.54 geheim") + full[ihdr_end:]


def test_truncated_png_is_closed_and_still_loses_its_text_chunks():
    full = _png_with_text()
    idat = full.index(b"IDAT")
    cut = full[: idat + 40]  # mitten im ersten Bilddaten-Chunk

    cleaned = sanitize_image(cut, "image/png", WITHOUT_LOCATION)

    assert cleaned.startswith(b"\x89PNG\r\n\x1a\n") and cleaned.endswith(_chunk(b"IEND", b""))
    assert b"geheim" not in cleaned and b"tEXt" not in cleaned
    with Image.open(io.BytesIO(cleaned)) as image:  # Kopf lesbar
        assert image.size == (64, 48)


def test_truncated_png_cut_inside_a_text_chunk_drops_it():
    full = _png_with_text()
    text = full.index(b"tEXt")
    cleaned = sanitize_image(full[: text + 12], "image/png", WITHOUT_LOCATION)
    assert b"geheim" not in cleaned and b"GPS" not in cleaned


def test_unfilterable_image_raises_the_expected_error_instead_of_a_server_error():
    with pytest.raises(ImageSanitizeError):
        sanitize_image(b"\x00\x00\x00\x18ftypheic" + b"\x00" * 20, "image/heic", WITHOUT_LOCATION)


def test_album_zip_skips_an_unfilterable_photo_and_the_single_download_is_422(db, monkeypatch):
    tenant = make_tenant(db)
    user = make_current_user(tenant.id, role="writer")
    asyncio.run(
        FileService().save_gallery_uploads(
            db, tenant_id=tenant.id, files=[("ganz.jpg", jpeg(color=(1, 120, 2))), ("kaputt.jpg", jpeg(color=(9, 9, 9)))],
            tags=[], created_by=None,
        )
    )
    stored = {f.original_name: f for f in db.scalars(select(StoredFile).where(StoredFile.tenant_id == tenant.id))}
    created = share_links_routes.create_share_link(ShareLinkCreate(name="Lager", file_ids=[f.public_id for f in stored.values()]), db, user)
    token = created.url.removeprefix("/share/")
    original = public_share_routes._public_file_bytes

    def failing(policy, stored_file):
        if stored_file.original_name == "kaputt.jpg":
            raise ImageSanitizeError("kaputt")
        return original(policy, stored_file)

    monkeypatch.setattr(public_share_routes, "_public_file_bytes", failing)

    with pytest.raises(HTTPException) as exc:
        public_share_routes.download_public_share_file(token, stored["kaputt.jpg"].public_id, _FakeRequest(), db)
    assert exc.value.status_code == 422 and exc.value.__cause__ is None
    everything = public_share_routes.download_public_share_all(token, _FakeRequest(), db)
    with zipfile.ZipFile(io.BytesIO(response_bytes(everything))) as archive:
        assert archive.namelist() == ["ganz.jpg"]
