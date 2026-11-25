"""Nachtlauf 2026-11-25 (dateien-fotos/fehlerbehandlung): ein abgeschnittenes JPEG (abgebrochene
Übertragung vom Handy) nimmt der Galerie-Upload an - nur ohne Vorschau. Im öffentlichen Link muss
es aber durch den Metadatenfilter (photo_metadata_privacy.sanitize_image), und der scheiterte an
der fehlenden EOI-Marke und danach auch an der Neukodierung (OSError «Truncated File Read»): Einzel-
Download und «Alle herunterladen» des ganzen Links endeten mit 500 und einem Fehlerprotokoll-Eintrag
je Abruf - ein beschädigtes Foto machte den ZIP des ganzen Albums unbrauchbar."""

import asyncio
import io
import random
import uuid
import zipfile

import pytest
from PIL import Image
from sqlalchemy import select

from app.api.routes import public_share as public_share_routes
from app.api.routes import share_links as share_links_routes
from app.core.config import settings
from app.models.entities import StoredFile
from app.schemas.files import ShareLinkCreate
from app.services import file_service as file_service_module
from app.services.file_service import FileService
from app.services.photo_metadata_privacy import MetadataPolicy, sanitize_image
from tests.factories import make_current_user, make_tenant
from tests.image_fixtures import build_exif, jpeg, response_bytes

GPS_IFD = 0x8825
MAKE = 0x010F


@pytest.fixture(autouse=True)
def _isolated_storage_root(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_root", str(tmp_path / "storage"))
    monkeypatch.setattr(settings, "upload_root", str(tmp_path / "storage" / "uploads"))
    monkeypatch.setattr(settings, "thumbnail_root", str(tmp_path / "thumbnails"))
    monkeypatch.setattr(file_service_module.scanner, "scan_bytes", lambda content, host, port: "clean")


class _FakeRequest:
    def __init__(self) -> None:
        self.client = type("C", (), {"host": f"198.51.100.{uuid.uuid4().int % 250}"})()
        self.headers: dict[str, str] = {}


def _truncated_jpeg_with_gps() -> bytes:
    """Handyfoto mit GPS und Kamera, abgeschnitten mitten in den Bilddaten (wie eine abgebrochene
    Übertragung): Rauschen, damit die Bilddaten den grössten Teil der Datei ausmachen."""
    rng = random.Random(7)
    noise = Image.frombytes("RGB", (160, 120), bytes(rng.randrange(256) for _ in range(160 * 120 * 3)))
    exif = build_exif(latitude=47.37, longitude=8.54, make="Testkamera")
    buffer = io.BytesIO()
    noise.save(buffer, format="JPEG", quality=90, exif=exif.tobytes())
    full = buffer.getvalue()
    scan_start = full.index(b"\xff\xda")
    cut = full[: scan_start + (len(full) - scan_start) // 2]
    assert len(cut) - scan_start > 5000  # Schnitt liegt sicher in den Bilddaten
    return cut


def _exif_of(content: bytes):
    with Image.open(io.BytesIO(content)) as image:  # liest nur den Kopf, dekodiert keine Pixel
        return image.getexif()


def test_sanitizer_keeps_a_truncated_jpeg_and_still_removes_location_and_camera():
    cut = _truncated_jpeg_with_gps()
    assert _exif_of(cut).get_ifd(GPS_IFD) and _exif_of(cut).get(MAKE) == "Testkamera"

    cleaned = sanitize_image(cut, "image/jpeg", MetadataPolicy(location=False, capture_date=True, camera=False))

    assert cleaned.startswith(b"\xff\xd8") and cleaned.endswith(b"\xff\xd9")
    exif = _exif_of(cleaned)
    assert not exif.get_ifd(GPS_IFD)
    assert exif.get(MAKE) is None
    assert b"Testkamera" not in cleaned


def test_public_link_with_a_truncated_photo_still_downloads(db):
    tenant = make_tenant(db)
    user = make_current_user(tenant.id, role="writer")
    asyncio.run(
        FileService().save_gallery_uploads(
            db, tenant_id=tenant.id, files=[("ganz.jpg", jpeg(color=(1, 120, 2))), ("kaputt.jpg", _truncated_jpeg_with_gps())],
            tags=[], created_by=None,
        )
    )
    stored = {f.original_name: f for f in db.scalars(select(StoredFile).where(StoredFile.tenant_id == tenant.id))}
    assert set(stored) == {"ganz.jpg", "kaputt.jpg"}  # der Upload nimmt das abgeschnittene Bild an
    # Standardfreigabe: ohne Standort und Kamera -> jede Datei läuft durch den Metadatenfilter
    created = share_links_routes.create_share_link(
        ShareLinkCreate(name="Lager", file_ids=[f.public_id for f in stored.values()]), db, user
    )
    token = created.url.removeprefix("/share/")

    single = public_share_routes.download_public_share_file(token, stored["kaputt.jpg"].public_id, _FakeRequest(), db)
    assert not _exif_of(response_bytes(single)).get_ifd(GPS_IFD)

    everything = public_share_routes.download_public_share_all(token, _FakeRequest(), db)
    with zipfile.ZipFile(io.BytesIO(response_bytes(everything))) as archive:
        assert sorted(archive.namelist()) == ["ganz.jpg", "kaputt.jpg"]
        assert b"Testkamera" not in archive.read("kaputt.jpg")
