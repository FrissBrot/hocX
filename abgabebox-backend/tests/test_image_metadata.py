"""Serverseitige Metadaten öffentlich eingereichter Bilder (app/image_metadata.py)."""

import io
from datetime import UTC, datetime

from PIL import Image
from PIL.TiffImagePlugin import IFDRational

from app import image_metadata


def _jpeg(exif: Image.Exif | None = None) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8)).save(buffer, format="JPEG", exif=exif.tobytes() if exif is not None else b"")
    return buffer.getvalue()


def test_reads_capture_date_offset_camera_and_southern_western_gps():
    exif = Image.Exif()
    exif[0x010F] = "Canon"
    exif[0x8769] = {0x9003: "2025:08:01 07:30:00", 0x9011: "-03:00"}
    exif[0x8825] = {
        1: "S", 2: (IFDRational(22, 1), IFDRational(54, 1), IFDRational(0, 1)),
        3: "W", 4: (IFDRational(43, 1), IFDRational(12, 1), IFDRational(0, 1)),
        5: b"\x01", 6: IFDRational(5, 1),
    }
    values = image_metadata.extract(_jpeg(exif))
    assert values["exif_taken_at"] == datetime(2025, 8, 1, 7, 30, tzinfo=UTC)
    assert values["exif_taken_offset"] == "-03:00"
    assert values["camera_make"] == "Canon"
    assert values["gps_latitude"] == -22.9 and values["gps_longitude"] == -43.2
    assert values["gps_altitude_m"] == -5.0
    assert values["metadata_scan_status"] == "ok" and values["gps_source"] == "server"


def test_missing_and_unreadable_metadata_are_distinguished():
    assert image_metadata.extract(_jpeg())["metadata_scan_status"] == "no_metadata"
    values = image_metadata.extract(b"kein bild")
    assert values["metadata_scan_status"] == "unreadable" and "exif_taken_at" not in values


def test_null_island_is_not_stored():
    exif = Image.Exif()
    zero = (IFDRational(0, 1), IFDRational(0, 1), IFDRational(0, 1))
    exif[0x8825] = {1: "N", 2: zero, 3: "E", 4: zero}
    assert "gps_latitude" not in image_metadata.extract(_jpeg(exif))
