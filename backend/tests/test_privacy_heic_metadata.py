"""Unkonvertierte HEIC-Dateien (Abgabebox speichert sie als image/heic) dürfen Metadaten, die der
Empfänger nicht sehen soll, genauso wenig mitliefern wie JPEG/PNG/WebP: öffentliche Links ohne
Standortfreigabe (Standard), Leser ohne GPS-Recht (Paket 9.4), Partner ohne Standortfreigabe
(IMGMETA-007)."""
from __future__ import annotations

import io

from PIL import Image

from app.api.routes import files as file_routes
from app.api.routes import public_share as public_share_routes
from app.api.routes import share_links as share_links_routes
from app.schemas.files import ShareLinkCreate
from app.services.photo_metadata_privacy import MetadataPolicy, sanitize_image
from tests.factories import make_current_user, make_tenant
from tests.image_fixtures import response_bytes
from tests.test_share_link_routes import _FakeRequest, _isolated_storage_root, _make_file  # noqa: F401  (Fixture)

_GPS = 0x8825


def _heic_with_gps() -> bytes:
    exif = Image.Exif()
    exif[0x0132] = "2026:07:01 10:00:00"
    exif[0x010F] = "Testkamera"
    exif[_GPS] = {1: "N", 2: (47.0, 22.0, 10.5), 3: "E", 4: (8.0, 32.0, 5.25)}
    buffer = io.BytesIO()
    Image.new("RGB", (40, 30), (120, 30, 200)).save(buffer, format="HEIF", exif=exif.tobytes())
    return buffer.getvalue()


def _exif_of(data: bytes) -> Image.Exif:
    with Image.open(io.BytesIO(data)) as image:
        return image.getexif()


def test_sanitize_image_drops_location_from_heic():
    original = _heic_with_gps()
    assert dict(_exif_of(original).get_ifd(_GPS))

    cleaned = sanitize_image(original, "image/heic", MetadataPolicy(location=False, capture_date=True, camera=True))

    assert dict(_exif_of(cleaned).get_ifd(_GPS)) == {}
    assert _exif_of(cleaned).get(0x010F) == "Testkamera"
    nothing = sanitize_image(original, "image/heic", MetadataPolicy(location=False, capture_date=False, camera=False))
    assert 0x010F not in _exif_of(nothing) and 0x0132 not in _exif_of(nothing)
    with Image.open(io.BytesIO(nothing)) as image:
        assert image.size == (40, 30) and not image.info.get("xmp")


def test_public_link_does_not_serve_heic_location(db):
    tenant = make_tenant(db)
    user = make_current_user(tenant.id, role="writer")
    photo = _make_file(db, tenant.id, "abgabe.heic", content=_heic_with_gps(), mime_type="image/heic")
    created = share_links_routes.create_share_link(ShareLinkCreate(name="Lager", file_ids=[photo.public_id]), db, user)
    assert created.share_location is False
    token = created.url.removeprefix("/share/")

    response = public_share_routes.download_public_share_file(token, photo.public_id, _FakeRequest(), db)

    assert dict(_exif_of(response_bytes(response)).get_ifd(_GPS)) == {}


def test_reader_does_not_get_heic_location(db, monkeypatch):
    monkeypatch.setattr(file_routes.access_service, "ensure_can_read_stored_file", lambda *args, **kwargs: None)
    tenant = make_tenant(db)
    photo = _make_file(db, tenant.id, "abgabe.heic", content=_heic_with_gps(), mime_type="image/heic")
    photo.scan_status = "clean"
    db.flush()

    response = file_routes.get_stored_file_content(photo.public_id, None, db, make_current_user(tenant.id, role="reader"))

    assert dict(_exif_of(response_bytes(response)).get_ifd(_GPS)) == {}
