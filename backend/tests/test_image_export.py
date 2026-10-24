"""Export mit geschätztem Aufnahmedatum (image_export_service) über Einzeldownload, Live-Photo-ZIP
und Freigabe-Links - gespeicherte Originale bleiben unverändert."""

import hashlib
import io
import zipfile
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from app.api.routes import files as files_routes
from app.api.routes import public_share as public_share_routes
from app.api.routes import share_links as share_links_routes
from app.core.config import settings
from app.models.entities import GalleryImage, StoredFile
from app.schemas.files import ShareLinkCreate
from app.services import image_export_service, image_metadata_service
from tests.factories import make_current_user, make_tenant
from tests.image_fixtures import gif, jpeg, png, read_exif, response_bytes, webp
from tests.test_share_link_routes import _FakeRequest


@pytest.fixture(autouse=True)
def _isolated_storage_root(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_root", str(tmp_path / "storage"))
    monkeypatch.setattr(settings, "upload_root", str(tmp_path / "storage" / "uploads"))
    monkeypatch.setattr(settings, "thumbnail_root", str(tmp_path / "thumbs"))


def _meta(mime="image/jpeg", **values):
    defaults = dict(
        mime_type=mime, exif_taken_at=None, estimated_taken_on=None, gps_latitude=None, gps_longitude=None,
        gps_altitude_m=None, gps_direction_deg=None,
    )
    defaults.update(values)
    return SimpleNamespace(**defaults)


def test_estimated_date_is_written_as_capture_date_with_documented_noon_convention_and_marker():
    original = jpeg(latitude=-41.29, longitude=174.78)
    exported = image_export_service.export_bytes(_meta(estimated_taken_on=date(1987, 4, 12)), original)
    assert exported is not None
    _, exif_ifd, gps = read_exif(exported)
    assert exif_ifd[0x9003] == "1987:04:12 12:00:00"
    assert 0x9011 not in exif_ifd  # keine erfundene Zeitzone
    assert b"hocx:CaptureDateEstimated=\"True\"" in exported
    assert b'photoshop:DateCreated="1987-04-12"' in exported  # XMP: reines Datum ohne Uhrzeit
    assert gps[1] == "S" and gps[3] == "E"  # vorhandenes GPS bleibt erhalten
    # Re-Import erkennt das Schätzdatum wieder als Schätzung, nicht als echtes Datum.
    reimported = image_metadata_service.extract_image_metadata(exported)
    assert reimported.taken_at is None
    assert reimported.estimated_taken_on == date(1987, 4, 12)
    assert reimported.gps_latitude == pytest.approx(-41.29, abs=1e-4)


def test_real_capture_date_is_never_replaced():
    original = jpeg(taken_at=datetime(2011, 11, 11, 11, 11))
    assert image_export_service.export_bytes(
        _meta(exif_taken_at=datetime(2011, 11, 11, 11, 11, tzinfo=UTC), estimated_taken_on=date(1990, 1, 1)), original
    ) is None
    # Auch wenn die Datenbank das Datum (noch) nicht kennt: ein Datum in der Datei gewinnt.
    assert image_export_service.export_bytes(_meta(estimated_taken_on=date(1990, 1, 1)), original) is None


def test_without_any_capture_date_nothing_is_invented():
    assert image_export_service.export_bytes(_meta(), jpeg()) is None


@pytest.mark.parametrize("builder, mime", [(png, "image/png"), (webp, "image/webp")])
def test_png_and_webp_receive_the_estimate(builder, mime):
    exported = image_export_service.export_bytes(_meta(mime=mime, estimated_taken_on=date(2002, 2, 2)), builder(latitude=10.0, longitude=-10.0))
    assert exported is not None
    _, exif_ifd, gps = read_exif(exported)
    assert exif_ifd[0x9003] == "2002:02:02 12:00:00"
    assert gps[3] == "W"
    with Image.open(io.BytesIO(exported)) as image:
        image.load()  # weiterhin gültiges Bild


def test_simple_webp_without_metadata_gets_extended_header():
    buffer = io.BytesIO()
    Image.new("RGB", (16, 9), "white").save(buffer, format="WEBP")
    exported = image_export_service.export_bytes(_meta(mime="image/webp", estimated_taken_on=date(2003, 3, 3)), buffer.getvalue())
    with Image.open(io.BytesIO(exported)) as image:
        assert image.size == (16, 9)
        assert image.getexif().get_ifd(0x8769)[0x9003] == "2003:03:03 12:00:00"


def test_gps_known_only_in_database_is_written_into_the_export():
    exported = image_export_service.export_bytes(_meta(gps_latitude=-33.5, gps_longitude=-70.25, gps_altitude_m=-12.0), jpeg())
    metadata = image_metadata_service.extract_image_metadata(exported)
    assert metadata.gps_latitude == pytest.approx(-33.5, abs=1e-5)
    assert metadata.gps_longitude == pytest.approx(-70.25, abs=1e-5)
    assert metadata.gps_altitude_m == pytest.approx(-12.0)
    assert metadata.taken_at is None


def test_unsupported_formats_are_exported_unchanged():
    assert image_export_service.export_bytes(_meta(mime="image/gif", estimated_taken_on=date(2000, 1, 1)), gif()) is None
    assert image_export_service.export_bytes(_meta(mime="image/tiff", estimated_taken_on=date(2000, 1, 1)), b"II*\x00") is None
    # Defekte Datei: kein Fehler, Original wird geliefert.
    assert image_export_service.export_bytes(_meta(estimated_taken_on=date(2000, 1, 1)), b"\xff\xd8broken") is None


# --- Routen -------------------------------------------------------------------------------


def _stored(db, tenant_id, content, name="bild.jpg", **values):
    root = Path(settings.storage_root)
    root.mkdir(parents=True, exist_ok=True)
    (root / name).write_bytes(content)
    row = StoredFile(
        tenant_id=tenant_id, original_name=name, mime_type="image/jpeg", storage_path=name,
        checksum_sha256=hashlib.sha256(content).hexdigest(), scan_status="clean", **values,
    )
    db.add(row)
    db.flush()
    db.add(GalleryImage(tenant_id=tenant_id, stored_file_id=row.id))
    db.flush()
    return row


def test_single_download_uses_a_temporary_export_and_keeps_the_original(db):
    tenant = make_tenant(db)
    content = jpeg()
    row = _stored(db, tenant.id, content, estimated_taken_on=date(1975, 5, 5))
    response = files_routes.download_stored_file(row.public_id, part="image", db=db, user=make_current_user(tenant.id))
    exported = response_bytes(response)
    # Exportfassung als Bytes, nie das gespeicherte Original
    assert getattr(response, "path", None) is None or Path(response.path).name != "bild.jpg"
    assert read_exif(exported)[1][0x9003] == "1975:05:05 12:00:00"
    assert (Path(settings.storage_root) / "bild.jpg").read_bytes() == content
    assert 'filename="bild.jpg"' in response.headers["content-disposition"]


def test_single_download_without_estimate_serves_the_original(db):
    tenant = make_tenant(db)
    row = _stored(db, tenant.id, jpeg())
    response = files_routes.download_stored_file(row.public_id, part="image", db=db, user=make_current_user(tenant.id))
    assert Path(response.path).name == "bild.jpg"


def test_public_share_zip_uses_the_date_logic_and_respects_the_privacy_switch(db):
    tenant = make_tenant(db)
    user = make_current_user(tenant.id, role="writer")
    a = _stored(db, tenant.id, jpeg(color=(1, 2, 3)), name="a.jpg", estimated_taken_on=date(1960, 6, 6))
    b = _stored(db, tenant.id, jpeg(color=(9, 9, 9), taken_at=datetime(2020, 2, 2, 2, 2)), name="b.jpg", exif_taken_at=datetime(2020, 2, 2, 2, 2, tzinfo=UTC))

    shared = share_links_routes.create_share_link(
        ShareLinkCreate(name="mit", file_ids=[a.public_id, b.public_id], share_location=True, share_capture_date=True, share_camera=True), db, user
    )
    response = public_share_routes.download_public_share_all(shared.url.removeprefix("/share/"), _FakeRequest(), db)
    with zipfile.ZipFile(response.path) as archive:
        assert read_exif(archive.read("a.jpg"))[1][0x9003] == "1960:06:06 12:00:00"
        assert read_exif(archive.read("b.jpg"))[1][0x9003] == "2020:02:02 02:02:00"

    hidden = share_links_routes.create_share_link(
        ShareLinkCreate(name="ohne", file_ids=[a.public_id], share_location=True, share_capture_date=False, share_camera=True), db, user
    )
    response = public_share_routes.download_public_share_all(hidden.url.removeprefix("/share/"), _FakeRequest(), db)
    with zipfile.ZipFile(response.path) as archive:
        exported = archive.read("a.jpg")
    assert 0x9003 not in read_exif(exported)[1]
    assert b"CaptureDateEstimated" not in exported


def test_public_share_never_exposes_database_gps_when_location_is_not_shared(db):
    tenant = make_tenant(db)
    user = make_current_user(tenant.id, role="writer")
    a = _stored(db, tenant.id, jpeg(), name="geo.jpg", gps_latitude=46.0, gps_longitude=7.0)
    link = share_links_routes.create_share_link(ShareLinkCreate(name="x", file_ids=[a.public_id]), db, user)  # Standort standardmässig aus
    response = public_share_routes.download_public_share_file(link.url.removeprefix("/share/"), a.public_id, _FakeRequest(), db)
    assert read_exif(response_bytes(response))[2] == {}
    page = public_share_routes.get_public_share(link.url.removeprefix("/share/"), _FakeRequest(), db)
    assert "gps" not in page.files[0].model_dump()


def _png_with_compressed_xmp(xmp: bytes) -> bytes:
    """PNG mit komprimiertem iTXt-XMP *nach* IDAT - Pillow liest es beim Upload nicht an."""
    import struct
    import zlib

    base = png()
    iend = base.rindex(b"IEND") - 4
    body = zlib.compress(xmp, 9)
    payload = b"XML:com.adobe.xmp\x00\x01\x00\x00\x00" + body
    chunk = struct.pack(">I", len(payload)) + b"iTXt" + payload + struct.pack(">I", zlib.crc32(b"iTXt" + payload) & 0xFFFFFFFF)
    return base[:iend] + chunk + base[iend:]


def test_png_export_does_not_inflate_oversized_compressed_xmp():
    """IMGMETA-002: Komprimiertes PNG-XMP wird nur bis zu einer festen Grenze entpackt -
    eine präparierte Datei (hier 256 MiB Nullbytes in ~250 KiB) darf den Export nicht aufblähen."""
    import tracemalloc

    bomb = _png_with_compressed_xmp(b"\0" * (256 * 1024 * 1024))
    assert len(bomb) < 2 * 1024 * 1024
    tracemalloc.start()
    try:
        exported = image_export_service.export_bytes(_meta("image/png", estimated_taken_on=date(2001, 2, 3)), bomb)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 32 * 1024 * 1024
    assert exported is None  # Original wird unverändert geliefert


def test_png_export_still_reads_small_compressed_xmp():
    xmp = b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF><rdf:Description rdf:about=""/></rdf:RDF></x:xmpmeta>'
    original = _png_with_compressed_xmp(xmp)
    exported = image_export_service.export_bytes(_meta("image/png", estimated_taken_on=date(2001, 2, 3)), original)
    assert exported is not None
    assert exported.count(b"XML:com.adobe.xmp") == 1  # altes XMP ersetzt, nicht verdoppelt
    assert b"hocx:CaptureDateEstimated" in exported


def test_gps_read_from_the_file_itself_needs_no_export():
    """IMGMETA-006: GPS aus der eigenen Datei (Server/Backfill) steht schon drin - kein Einlesen,
    keine Temp-Kopie. Client-GPS und konvertierte HEIC-Dateien werden weiter exportiert."""
    gps = dict(gps_latitude=47.0, gps_longitude=8.0)
    assert not image_export_service.needs_export_processing(_meta(gps_source="server", **gps))
    assert not image_export_service.needs_export_processing(_meta(gps_source="backfill", checksum_sha256="a", source_checksum_sha256="a", **gps))
    assert image_export_service.needs_export_processing(_meta(gps_source="client", **gps))
    assert image_export_service.needs_export_processing(_meta(gps_source="server", checksum_sha256="jpg", source_checksum_sha256="heic", **gps))


def test_single_download_with_server_gps_serves_the_original(db):
    tenant = make_tenant(db)
    content = jpeg(latitude=47.0, longitude=8.0)
    row = _stored(db, tenant.id, content, gps_latitude=47.0, gps_longitude=8.0, gps_source="server")
    response = files_routes.download_stored_file(row.public_id, part="image", db=db, user=make_current_user(tenant.id))
    assert Path(response.path).name == "bild.jpg"
