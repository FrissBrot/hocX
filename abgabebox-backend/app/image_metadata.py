"""Aufnahmedatum, GPS und Kamera aus öffentlich eingereichten Bildern.

Bewusst eine kleine, eigenständige Kopie der Kernlogik aus
backend/app/services/image_metadata_service.py (gleiche Konventionen: lokale Kamerazeit ohne
Zeitzone, Offset separat, Süd/West negativ, (0, 0) = kein Fix) - dieser Dienst teilt keinen
Code mit dem Haupt-Backend (siehe _read_upload_within_limit in routes/public.py).

Die Abgabebox bietet keinen Vorab-Abgleich per Hash an: Hochladende sind anonym, und die
Antwort verrät absichtlich nicht, ob eine Datei schon vorhanden war. Die Metadaten werden
deshalb ausschliesslich hier, serverseitig, aus den empfangenen Bytes gelesen.
"""

from __future__ import annotations

import io
import re
from datetime import UTC, date, datetime, timedelta
from typing import Any

from PIL import Image

_DATETIME_RE = re.compile(r"^\s*(\d{4})[:\-](\d{2})[:\-](\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?")
_OFFSET_RE = re.compile(r"^([+-])(\d{2}):?(\d{2})$")
_MIN_DATE = date(1826, 1, 1)


def _parse_datetime(raw: Any) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("ascii", "ignore")
    match = _DATETIME_RE.match(str(raw).replace("\x00", ""))
    if not match:
        return None
    try:
        parsed = datetime(*(int(part or 0) for part in match.groups()))
    except ValueError:
        return None
    if parsed.date() < _MIN_DATE or parsed > datetime.now(UTC).replace(tzinfo=None) + timedelta(days=1):
        return None
    return parsed


def _offset(raw: Any) -> str | None:
    match = _OFFSET_RE.match(str(raw or "").strip())
    if not match or int(match.group(2)) > 14 or int(match.group(3)) >= 60:
        return None
    return f"{match.group(1)}{match.group(2)}:{match.group(3)}"


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return None if number != number else number


def _degrees(value: Any) -> float | None:
    if isinstance(value, (tuple, list)) and value:
        parts = [_number(part) for part in value]
        if any(part is None for part in parts):
            return None
        return parts[0] + (parts[1] / 60 if len(parts) > 1 else 0) + (parts[2] / 3600 if len(parts) > 2 else 0)
    return _number(value)


def _text(value: Any) -> str | None:
    text = str(value).replace("\x00", "").strip()[:120] if value is not None else ""
    return text or None


def extract(content: bytes) -> dict[str, Any]:
    """Spaltenwerte für stored_file (nur gefundene, plausible Werte) inkl.
    metadata_scanned_at/metadata_scan_status. Nicht lesbare Dateien -> nur der Status."""
    now = datetime.now(UTC)
    try:
        with Image.open(io.BytesIO(content)) as image:
            exif = image.getexif()
            values: dict[str, Any] = {}
            if len(exif):
                exif_ifd = exif.get_ifd(0x8769)
                for tag, offset_tag in ((0x9003, 0x9011), (0x9004, 0x9012)):
                    taken_at = _parse_datetime(exif_ifd.get(tag))
                    if taken_at is not None:
                        values["exif_taken_at"] = taken_at.replace(tzinfo=UTC)
                        values["exif_taken_offset"] = _offset(exif_ifd.get(offset_tag) or exif_ifd.get(0x9010))
                        break
                else:
                    taken_at = _parse_datetime(exif.get(0x0132))
                    if taken_at is not None:
                        values["exif_taken_at"] = taken_at.replace(tzinfo=UTC)
                if "exif_taken_at" in values:
                    values["exif_taken_source"] = "server"
                values["camera_make"] = _text(exif.get(0x010F))
                values["camera_model"] = _text(exif.get(0x0110))
                orientation = exif.get(0x0112)
                values["orientation"] = orientation if isinstance(orientation, int) and 1 <= orientation <= 8 else None
                gps = exif.get_ifd(0x8825)
                latitude, longitude = _degrees(gps.get(2)), _degrees(gps.get(4))
                if latitude is not None and longitude is not None:
                    if str(gps.get(1, "")).upper().startswith("S"):
                        latitude = -abs(latitude)
                    if str(gps.get(3, "")).upper().startswith("W"):
                        longitude = -abs(longitude)
                    if -90 <= latitude <= 90 and -180 <= longitude <= 180 and (latitude, longitude) != (0.0, 0.0):
                        values["gps_latitude"] = round(latitude, 7)
                        values["gps_longitude"] = round(longitude, 7)
                        values["gps_source"] = "server"
                        altitude = _number(gps.get(6))
                        if altitude is not None and -12000 <= altitude <= 60000:
                            ref = gps.get(5)
                            below = ref in (1, b"\x01") or (isinstance(ref, bytes) and ref[:1] == b"\x01")
                            values["gps_altitude_m"] = -abs(altitude) if below else altitude
                        direction = _number(gps.get(17))
                        if direction is not None and 0 <= direction <= 360:
                            values["gps_direction_deg"] = round(direction % 360, 3)
            values = {key: value for key, value in values.items() if value is not None}
            found = any(key in values for key in ("exif_taken_at", "gps_latitude", "camera_make", "camera_model"))
            values["metadata_scan_status"] = "ok" if found else "no_metadata"
    except Exception:
        values = {"metadata_scan_status": "unreadable"}
    values["metadata_scanned_at"] = now
    return values
