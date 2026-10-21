"""Datenschutz-Audit Paket 9.3/9.4/9.5: «GPS-Daten des Bildes mitsenden» beim Upload, GPS erst ab
writer, Datenstandort der Speicherprofile, Datenschutz-Link für die Abgabebox."""
from __future__ import annotations

import asyncio
import io
import struct
import zlib

import pytest
from PIL import Image
from pydantic import ValidationError

from app.api.routes import files as file_routes
from app.api.routes.privacy_settings import PrivacySettingsWrite
from app.core.config import settings
from app.models import StorageProfile, StoredFile
from app.services import public_id_service, storage_profile_service as sps
from app.services.file_service import FileService
from app.services.gps_strip import strip_gps
from tests.factories import make_current_user, make_tenant

_GPS = 0x8825


@pytest.fixture(autouse=True)
def _isolated_storage(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(settings, "upload_root", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "thumbnail_root", str(tmp_path / "thumbnails"))


def _exif_with_gps() -> Image.Exif:
    exif = Image.Exif()
    exif[0x0132] = "2026:07:01 10:00:00"
    exif[0x010F] = "Testkamera"
    exif[_GPS] = {1: "N", 2: (47.0, 22.0, 10.5), 3: "E", 4: (8.0, 32.0, 5.25), 6: 408.0}
    return exif


def _image(fmt: str) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (40, 30), (120, 30, 200)).save(buffer, format=fmt, exif=_exif_with_gps().tobytes())
    return buffer.getvalue()


def _gps_of(data: bytes) -> dict:
    with Image.open(io.BytesIO(data)) as image:
        return dict(image.getexif().get_ifd(_GPS))


@pytest.mark.parametrize("fmt", ["JPEG", "PNG", "WEBP", "HEIF"])
def test_strip_gps_removes_only_the_location(fmt):
    original = _image(fmt)
    assert _gps_of(original)

    stripped = strip_gps(original)

    assert len(stripped) == len(original)
    assert _gps_of(stripped) == {}
    with Image.open(io.BytesIO(stripped)) as image:
        image.load()
        assert image.getexif().get(0x0132) == "2026:07:01 10:00:00" and image.getexif().get(0x010F) == "Testkamera"
        assert image.size == (40, 30)


def test_strip_gps_keeps_png_chunks_valid_and_scrubs_xmp_and_video_locations():
    png = strip_gps(_image("PNG"))
    position = 8
    while position < len(png):
        (length,) = struct.unpack_from(">I", png, position)
        crc = struct.unpack_from(">I", png, position + 8 + length)[0]
        assert zlib.crc32(png[position + 4:position + 8 + length]) & 0xFFFFFFFF == crc
        position += 12 + length

    xmp = b'<x:xmpmeta><rdf:Description exif:GPSLatitude="47,22.17N" exif:GPSLongitude="8,32.08E"/></x:xmpmeta>'
    assert b"47,22" not in strip_gps(b"\xff\xd8" + xmp)
    video = b"\x00\x00\x00\x1c\xa9xyz\x00\x12\x15\xc7+47.3769+008.5417+408.000/moov"
    assert b"+47.3769" not in strip_gps(video, "video/mp4") and len(strip_gps(video, "video/mp4")) == len(video)
    assert strip_gps(video, "image/jpeg") == video  # Bilddaten werden nie nach Text durchsucht


def test_manipulated_exif_cannot_stall_the_upload():
    import time

    pattern = b"Exif\x00\x00II*\x00\x08\x00\x00\x00\xff\xff"
    hostile = b"\xff\xd8\xff\xe1" + pattern * 200_000  # ~3 MB, jeder Block mit 65535 angeblichen Einträgen
    started = time.monotonic()
    assert len(strip_gps(hostile)) == len(hostile)
    assert time.monotonic() - started < 5


def test_gallery_upload_without_gps_keeps_date_but_no_location(db):
    tenant = make_tenant(db)
    service = FileService()

    with_gps, _ = asyncio.run(service.save_gallery_uploads(db, tenant_id=tenant.id, files=[("mit.jpg", _image("JPEG"))], tags=[], created_by=None))
    without_gps, _ = asyncio.run(service.save_gallery_uploads(
        db, tenant_id=tenant.id, files=[("ohne.heic", _image("HEIF"))], tags=[], created_by=None, include_gps=False,
    ))

    kept = public_id_service.get_by_public_id(db, StoredFile, with_gps[0].id)
    removed = public_id_service.get_by_public_id(db, StoredFile, without_gps[0].id)
    assert kept.gps_latitude is not None
    assert removed.gps_latitude is None and removed.exif_taken_at is not None
    from app.core.storage import MAIN, read_bytes_or_404

    assert _gps_of(read_bytes_or_404(MAIN, removed.storage_path)) == {}


def test_readers_do_not_see_gps(db, monkeypatch):
    # Zugriffsrechte auf die Galerie sind nicht Teil dieses Tests (eigene Tests in test_files_*).
    monkeypatch.setattr(file_routes.access_service, "ensure_can_read_stored_file", lambda *args, **kwargs: None)
    tenant = make_tenant(db)
    items, _ = asyncio.run(FileService().save_gallery_uploads(db, tenant_id=tenant.id, files=[("mit.jpg", _image("JPEG"))], tags=[], created_by=None))
    file_id = items[0].id

    writer = file_routes.get_stored_file_metadata(file_id, db, make_current_user(tenant.id, role="writer"))
    reader = file_routes.get_stored_file_metadata(file_id, db, make_current_user(tenant.id, role="reader"))

    assert writer.gps is not None and reader.gps is None
    stored = public_id_service.get_by_public_id(db, StoredFile, file_id)
    assert file_routes._strips_location(db, make_current_user(tenant.id, role="reader"), stored) is True


def test_privacy_notice_url_must_be_https():
    assert PrivacySettingsWrite(privacy_notice_url="https://verein.example/datenschutz").privacy_notice_url
    assert PrivacySettingsWrite(privacy_notice_url="").privacy_notice_url == ""
    for bad in ("http://verein.example", "javascript:alert(1)", "https://"):
        with pytest.raises(ValidationError):
            PrivacySettingsWrite(privacy_notice_url=bad)


# --- Datenstandort der Speicherprofile (E3) --------------------------------------------------


@pytest.mark.parametrize(
    ("provider", "region", "expected"),
    [("aws_s3", "eu-central-2", "ch"), ("aws_s3", "eu-west-1", "eu_eea"), ("aws_s3", "us-east-1", "third_country"),
     ("hetzner", "fsn1", "eu_eea"), ("s3_compatible", "x", None), ("garage_local", None, "ch")],
)
def test_location_is_derived_from_provider_and_region(provider, region, expected):
    assert sps.derive_location(provider, region) == expected


def test_third_country_needs_basis_and_confirmation(monkeypatch):
    profile = StorageProfile(provider="aws_s3", region="us-east-1")

    with pytest.raises(sps.StorageProfileError):
        sps._apply_location(profile, {}, actor_email="owner@hocx.invalid")
    with pytest.raises(sps.StorageProfileError):
        sps._apply_location(profile, {"transfer_basis": "Standardvertragsklauseln"}, actor_email="owner@hocx.invalid")
    sps._apply_location(profile, {"transfer_basis": "Standardvertragsklauseln", "location_confirmed": True}, actor_email="owner@hocx.invalid")
    assert profile.data_location == "third_country" and profile.location_confirmed_by == "owner@hocx.invalid"

    monkeypatch.setattr(settings, "storage_allowed_locations", "ch,eu_eea")
    with pytest.raises(sps.StorageProfileError):
        sps._apply_location(StorageProfile(provider="aws_s3", region="us-east-1", transfer_basis="SCC"), {"location_confirmed": True}, actor_email=None)
    custom = StorageProfile(provider="s3_compatible")
    with pytest.raises(sps.StorageProfileError):
        sps._apply_location(custom, {}, actor_email=None)
    sps._apply_location(custom, {"data_location": "ch"}, actor_email=None)
    assert custom.data_location == "ch"


def test_s3_writes_request_server_side_encryption():
    from app.core.objstore_client import ProfileConfig, S3Backend

    backend = S3Backend(ProfileConfig(profile_id=1, generation=1, provider="aws_s3", region="eu-central-2", bucket="b",
                                      access_key="a", secret_key="s", server_side_encryption=True))
    plain = S3Backend(ProfileConfig(profile_id=2, generation=1, provider="aws_s3", region="eu-central-2", bucket="b", access_key="a", secret_key="s"))

    assert backend._encryption_args() == {"ServerSideEncryption": "AES256"} and plain._encryption_args() == {}


def test_abgabebox_reads_only_the_notice_of_its_own_link(db):
    import secrets as _secrets

    from sqlalchemy import text

    from app.models import SubmissionLink, Tenant

    own = make_tenant(db, "Eigener Verein")
    other = make_tenant(db, "Anderer Verein")
    db.get(Tenant, own.id).privacy_notice_url = "https://eigen.example/datenschutz"
    db.get(Tenant, other.id).privacy_notice_url = "https://fremd.example/datenschutz"
    token = _secrets.token_urlsafe(24)
    db.add(SubmissionLink(tenant_id=own.id, name="Link", token=token))
    db.flush()

    db.execute(text("SET LOCAL ROLE hocx_abgabebox"))
    try:
        db.execute(text("SELECT set_config('app.abgabebox_link', :token, true)"), {"token": token})
        rows = db.execute(text("SELECT tenant_name, privacy_notice_url FROM abgabebox_privacy_notice()")).all()
        db.execute(text("SELECT set_config('app.abgabebox_link', '', true)"))
        without_link = db.execute(text("SELECT * FROM abgabebox_privacy_notice()")).all()
    finally:
        db.execute(text("RESET ROLE"))

    assert [tuple(row) for row in rows] == [("Eigener Verein", "https://eigen.example/datenschutz")]
    assert without_link == []
