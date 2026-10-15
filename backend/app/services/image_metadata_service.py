"""Bild-Metadaten: serverseitige Extraktion, Validierung und das Ergänzen fehlender Werte.

Ein gemeinsamer Ort für alles, was Aufnahmedatum, GPS, Kamera und Abmessungen eines Bildes
betrifft - genutzt von Upload (Galerie, Protokollbilder), Vorab-Abgleich
(POST /files/upload-precheck), Backfill und Metadatenanzeige.

Grundregeln (siehe backend/UPLOAD_DUPLICATES.md):

1. Vorhandene gültige Werte werden nie still überschrieben. Fehlende Werte werden ergänzt,
   abweichende Werte als Konflikt gemeldet und verworfen.
2. Werte aus dem Browser sind nicht vertrauenswürdig. Ist das Original byte-identisch auf dem
   Server vorhanden (checksum_sha256 passt), wird stattdessen die Datei selbst analysiert -
   der Client-Wert dient nur als Auslöser. Nur wenn das Original nicht mehr existiert
   (HEIC/HEIF wurde beim Upload nach JPEG konvertiert, Treffer über source_checksum_sha256),
   werden validierte Client-Werte mit Herkunft "client" übernommen.
3. Datumswerte ohne Zeitzone bleiben lokale Kamerazeit ("floating", als UTC gespeichert, siehe
   StoredFile.exif_taken_at); ein EXIF-Offset wird separat gespeichert, nie eingerechnet.
4. GPS-Koordinaten sind WGS84-Dezimalgrad, Süd/West negativ. (0, 0) gilt als "kein Fix".
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Iterable, Literal

from PIL import Image

# Registriert den HEIC/HEIF-Opener für PIL (Seiteneffekt des Imports), damit HEIC-Originale
# vor der JPEG-Konvertierung direkt analysiert werden können.
from app.services import apple_media  # noqa: F401

MetadataSource = Literal["server", "client", "backfill"]
ScanStatus = Literal["ok", "no_metadata", "unreadable", "missing_file", "source_unavailable"]

# Feldgruppen, wie sie in API-Antworten ("applied"/"conflicts") erscheinen.
FIELD_TAKEN_AT = "taken_at"
FIELD_GPS = "gps"
FIELD_CAMERA = "camera"
FIELD_DIMENSIONS = "dimensions"
FIELD_ORIENTATION = "orientation"
FIELD_ESTIMATED = "estimated_taken_on"

# Älteste plausible Aufnahme (erste erhaltene Fotografie 1826/27); Zukunft max. 1 Tag
# Toleranz für Zeitzonen.
MIN_CAPTURE_DATE = date(1826, 1, 1)
_MAX_FUTURE = timedelta(days=1)
MIN_ALTITUDE_M = -12_000.0
MAX_ALTITUDE_M = 60_000.0
MAX_ACCURACY_M = 100_000.0
MAX_DIMENSION = 100_000
MAX_TEXT_LENGTH = 120
# Abweichungen unterhalb dieser Schwellen gelten als "gleicher Wert" (Rundung, Parser).
_GPS_TOLERANCE_DEG = 1e-5
_TIME_TOLERANCE = timedelta(seconds=1)

_EXIF_IFD = 0x8769
_GPS_IFD = 0x8825
_TAG_MAKE = 0x010F
_TAG_MODEL = 0x0110
_TAG_ORIENTATION = 0x0112
_TAG_DATETIME = 0x0132
_TAG_DATETIME_ORIGINAL = 0x9003
_TAG_DATETIME_DIGITIZED = 0x9004
_TAG_OFFSET_TIME = 0x9010
_TAG_OFFSET_TIME_ORIGINAL = 0x9011
_TAG_OFFSET_TIME_DIGITIZED = 0x9012

_EXIF_DATETIME_RE = re.compile(r"^\s*(\d{4})[:\-](\d{2})[:\-](\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?")
_OFFSET_RE = re.compile(r"^([+-])(\d{2}):?(\d{2})$")
_XMP_ATTR_RE = r'{name}\s*=\s*"([^"]+)"|<{name}>([^<]+)</{name}>'
# Markierung, die hocX beim Export eines nur geschätzten Datums ins XMP schreibt (siehe
# image_export_service.py). Wird ein so exportiertes Bild wieder hochgeladen, darf das
# technisch eingetragene 12:00-Datum nicht als echtes Aufnahmedatum gelten.
HOCX_XMP_NAMESPACE = "https://hocx.ch/ns/capture/1.0/"
_HOCX_ESTIMATED_RE = re.compile(r'hocx:CaptureDateEstimated\s*=\s*"True"|<hocx:CaptureDateEstimated>True<', re.IGNORECASE)
_HOCX_ESTIMATED_DATE_RE = re.compile(r'hocx:EstimatedCaptureDate\s*=\s*"(\d{4}-\d{2}-\d{2})"|<hocx:EstimatedCaptureDate>(\d{4}-\d{2}-\d{2})<')


@dataclass
class ImageMetadata:
    """Validierte Metadaten eines Bildes - jedes Feld optional. `taken_at` ist naive lokale
    Kamerazeit; `estimated_taken_on` kommt nur aus Benutzereingaben oder einer hocX-XMP-Markierung."""

    width: int | None = None
    height: int | None = None
    taken_at: datetime | None = None
    taken_offset: str | None = None
    camera_make: str | None = None
    camera_model: str | None = None
    orientation: int | None = None
    gps_latitude: float | None = None
    gps_longitude: float | None = None
    gps_altitude_m: float | None = None
    gps_direction_deg: float | None = None
    gps_accuracy_m: float | None = None
    gps_timestamp: datetime | None = None
    estimated_taken_on: date | None = None
    status: ScanStatus = "ok"

    @property
    def has_capture_metadata(self) -> bool:
        return any(
            value is not None
            for value in (self.taken_at, self.gps_latitude, self.camera_make, self.camera_model, self.estimated_taken_on)
        )

    @property
    def camera_label(self) -> str | None:
        parts = [p for p in (self.camera_make, self.camera_model) if p]
        if len(parts) == 2 and parts[1].lower().startswith(parts[0].lower()):
            return parts[1]
        return " ".join(parts) or None


@dataclass
class MergeOutcome:
    applied: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)

    def add_applied(self, name: str) -> None:
        if name not in self.applied:
            self.applied.append(name)

    def add_conflict(self, name: str) -> None:
        if name not in self.conflicts:
            self.conflicts.append(name)

    def extend(self, other: "MergeOutcome") -> None:
        for name in other.applied:
            self.add_applied(name)
        for name in other.conflicts:
            self.add_conflict(name)


# --- Validierung --------------------------------------------------------------------------


def _now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def valid_capture_datetime(value: datetime | None) -> datetime | None:
    """Naive Kamerazeit, wenn plausibel (1826 bis morgen), sonst None."""
    if value is None:
        return None
    naive = value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo is not None else value
    if naive.date() < MIN_CAPTURE_DATE or naive > _now_naive() + _MAX_FUTURE:
        return None
    return naive


def valid_estimated_date(value: date | None) -> date | None:
    """Geschätztes Datum: 1826 bis heute (eine Schätzung in der Zukunft ist ein Tippfehler)."""
    if value is None:
        return None
    if value < MIN_CAPTURE_DATE or value > (datetime.now(UTC) + _MAX_FUTURE).date():
        return None
    return value


def valid_offset(value: str | None) -> str | None:
    if not value:
        return None
    match = _OFFSET_RE.match(value.strip())
    if not match:
        return None
    sign, hours, minutes = match.groups()
    if int(hours) > 14 or int(minutes) >= 60:
        return None
    return f"{sign}{hours}:{minutes}"


def valid_coordinates(latitude: float | None, longitude: float | None) -> tuple[float, float] | None:
    if latitude is None or longitude is None:
        return None
    try:
        lat, lon = float(latitude), float(longitude)
    except (TypeError, ValueError):
        return None
    if lat != lat or lon != lon:  # NaN
        return None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None
    if lat == 0.0 and lon == 0.0:
        return None  # "Null Island": typischer Platzhalter ohne GPS-Fix
    return round(lat, 7), round(lon, 7)


def _valid_float(value: Any, low: float, high: float) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or not (low <= number <= high):
        return None
    return number


def valid_direction(value: Any) -> float | None:
    number = _valid_float(value, 0.0, 360.0)
    if number is None:
        return None
    # Erst runden, dann Modulo: 359.9996 ergäbe sonst 360.0 und verletzte ck_stored_file_gps_direction.
    return round(number, 3) % 360.0


def valid_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\x00", "").strip()
    return text[:MAX_TEXT_LENGTH] or None


def valid_dimension(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if 1 <= number <= MAX_DIMENSION else None


def valid_orientation(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if 1 <= number <= 8 else None


def parse_exif_datetime(raw: Any) -> datetime | None:
    """"YYYY:MM:DD HH:MM:SS" (auch mit "-"/"T", ohne Sekunden, mit Subsekunden/Offset-Rest)
    -> naive datetime. "0000:00:00 00:00:00" und Unplausibles -> None."""
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("ascii", "ignore")
    match = _EXIF_DATETIME_RE.match(str(raw).replace("\x00", ""))
    if not match:
        return None
    year, month, day, hour, minute, second = match.groups()
    try:
        parsed = datetime(int(year), int(month), int(day), int(hour), int(minute), int(second or 0))
    except ValueError:
        return None
    return valid_capture_datetime(parsed)


def _rational(value: Any) -> float | None:
    try:
        if isinstance(value, tuple) and len(value) == 2 and not hasattr(value[0], "numerator"):
            numerator, denominator = value
            return float(numerator) / float(denominator) if float(denominator) else None
        number = float(value)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return None if number != number else number


def _dms_to_degrees(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (tuple, list)):
        parts = [_rational(part) for part in value]
        if not parts or any(part is None for part in parts):
            return None
        degrees = parts[0] + (parts[1] / 60.0 if len(parts) > 1 else 0.0) + (parts[2] / 3600.0 if len(parts) > 2 else 0.0)
        return degrees
    return _rational(value)


def _ref(value: Any) -> str:
    if isinstance(value, bytes):
        value = value.decode("ascii", "ignore")
    return str(value or "").strip().upper()[:1]


def gps_from_exif_ifd(gps: dict[int, Any]) -> dict[str, Any]:
    """GPS-IFD (Tag -> Wert) -> validierte Felder. Süd (S) und West (W) werden negativ, eine
    Höhe mit AltitudeRef 1 liegt unter dem Meeresspiegel. Leeres Dict, wenn keine gültigen
    Koordinaten enthalten sind."""
    if not gps:
        return {}
    latitude = _dms_to_degrees(gps.get(2))
    longitude = _dms_to_degrees(gps.get(4))
    if latitude is not None and _ref(gps.get(1)) == "S":
        latitude = -abs(latitude)
    if longitude is not None and _ref(gps.get(3)) == "W":
        longitude = -abs(longitude)
    coordinates = valid_coordinates(latitude, longitude)
    if coordinates is None:
        return {}
    result: dict[str, Any] = {"gps_latitude": coordinates[0], "gps_longitude": coordinates[1]}
    altitude = _rational(gps.get(6))
    if altitude is not None:
        ref = gps.get(5)
        if isinstance(ref, bytes):
            ref = ref[:1] == b"\x01"
        if ref in (1, True, "1"):
            altitude = -abs(altitude)
        result["gps_altitude_m"] = _valid_float(altitude, MIN_ALTITUDE_M, MAX_ALTITUDE_M)
    result["gps_direction_deg"] = valid_direction(_rational(gps.get(17)))
    result["gps_accuracy_m"] = _valid_float(_rational(gps.get(31)), 0.0, MAX_ACCURACY_M)
    date_stamp, time_stamp = gps.get(29), gps.get(7)
    if date_stamp and isinstance(time_stamp, (tuple, list)) and len(time_stamp) == 3:
        parts = [_rational(part) for part in time_stamp]
        try:
            day = datetime.strptime(str(date_stamp).strip()[:10].replace("-", ":"), "%Y:%m:%d")
            if None not in parts:
                stamp = day + timedelta(hours=parts[0], minutes=parts[1], seconds=parts[2])
                if valid_capture_datetime(stamp) is not None:
                    result["gps_timestamp"] = stamp.replace(tzinfo=UTC, microsecond=0)
        except (ValueError, TypeError, OverflowError):
            pass
    return {key: value for key, value in result.items() if value is not None}


def _xmp_value(xmp: str, name: str) -> str | None:
    match = re.search(_XMP_ATTR_RE.format(name=re.escape(name)), xmp)
    if not match:
        return None
    return (match.group(1) or match.group(2) or "").strip() or None


def _parse_xmp_datetime(raw: str | None) -> tuple[datetime | None, str | None]:
    """ISO-8601 aus XMP. Ein reines Datum ("2024-05-01") ist KEIN Aufnahmezeitpunkt und wird
    ignoriert - sonst entstünde eine erfundene Uhrzeit."""
    if not raw or len(raw) < 16:
        return None, None
    taken_at = parse_exif_datetime(raw)
    offset_match = re.search(r"([+-]\d{2}:?\d{2})$", raw)
    offset = valid_offset(offset_match.group(1)) if offset_match else ("+00:00" if raw.endswith("Z") else None)
    return taken_at, offset


def _xmp_text(image: Image.Image) -> str | None:
    raw = image.info.get("xmp") or image.info.get("XML:com.adobe.xmp")
    if raw is None:
        return None
    if isinstance(raw, bytes):
        return raw.decode("utf-8", "ignore")
    return str(raw)


def extract_image_metadata(content: bytes) -> ImageMetadata:
    """Serverseitige Analyse (EXIF, GPS-IFD, XMP-Fallback) für JPEG, PNG, WebP, TIFF, GIF,
    BMP und HEIC/HEIF. status "unreadable", wenn PIL die Datei nicht öffnen kann,
    "no_metadata", wenn sie lesbar ist, aber weder Datum, GPS noch Kamera trägt."""
    try:
        with Image.open(io.BytesIO(content)) as image:
            metadata = ImageMetadata(width=valid_dimension(image.width), height=valid_dimension(image.height))
            try:
                exif = image.getexif()
            except Exception:
                exif = None
            if exif is not None and len(exif):
                metadata.camera_make = valid_text(exif.get(_TAG_MAKE))
                metadata.camera_model = valid_text(exif.get(_TAG_MODEL))
                metadata.orientation = valid_orientation(exif.get(_TAG_ORIENTATION))
                try:
                    exif_ifd = exif.get_ifd(_EXIF_IFD)
                except Exception:
                    exif_ifd = {}
                for tag, offset_tag in (
                    (_TAG_DATETIME_ORIGINAL, _TAG_OFFSET_TIME_ORIGINAL),
                    (_TAG_DATETIME_DIGITIZED, _TAG_OFFSET_TIME_DIGITIZED),
                ):
                    taken_at = parse_exif_datetime(exif_ifd.get(tag))
                    if taken_at is not None:
                        metadata.taken_at = taken_at
                        metadata.taken_offset = valid_offset(exif_ifd.get(offset_tag) or exif_ifd.get(_TAG_OFFSET_TIME))
                        break
                if metadata.taken_at is None:
                    # IFD0 DateTime ist streng genommen "zuletzt geändert", in der Praxis bei
                    # Kamera-JPEGs aber die Aufnahmezeit - bisheriges Verhalten beibehalten.
                    metadata.taken_at = parse_exif_datetime(exif.get(_TAG_DATETIME))
                    if metadata.taken_at is not None:
                        metadata.taken_offset = valid_offset(exif_ifd.get(_TAG_OFFSET_TIME))
                try:
                    gps = exif.get_ifd(_GPS_IFD)
                except Exception:
                    gps = {}
                for key, value in gps_from_exif_ifd(dict(gps)).items():
                    setattr(metadata, key, value)
            xmp = _xmp_text(image)
            if xmp:
                _apply_xmp(metadata, xmp)
    except Exception:
        return ImageMetadata(status="unreadable")
    if not metadata.has_capture_metadata:
        metadata.status = "no_metadata"
    return metadata


def _apply_xmp(metadata: ImageMetadata, xmp: str) -> None:
    if _HOCX_ESTIMATED_RE.search(xmp):
        # Von hocX exportiertes Schätzdatum: das technisch eingetragene EXIF-Datum ist kein
        # echtes Aufnahmedatum (siehe image_export_service).
        match = _HOCX_ESTIMATED_DATE_RE.search(xmp)
        estimated = match and (match.group(1) or match.group(2))
        metadata.taken_at = None
        metadata.taken_offset = None
        if estimated:
            try:
                metadata.estimated_taken_on = valid_estimated_date(date.fromisoformat(estimated))
            except ValueError:
                pass
        return
    if metadata.taken_at is None:
        for name in ("exif:DateTimeOriginal", "photoshop:DateCreated", "xmp:CreateDate"):
            taken_at, offset = _parse_xmp_datetime(_xmp_value(xmp, name))
            if taken_at is not None:
                metadata.taken_at, metadata.taken_offset = taken_at, offset
                break
    if metadata.gps_latitude is None:
        latitude = _parse_xmp_coordinate(_xmp_value(xmp, "exif:GPSLatitude"))
        longitude = _parse_xmp_coordinate(_xmp_value(xmp, "exif:GPSLongitude"))
        coordinates = valid_coordinates(latitude, longitude)
        if coordinates is not None:
            metadata.gps_latitude, metadata.gps_longitude = coordinates
    if metadata.camera_make is None:
        metadata.camera_make = valid_text(_xmp_value(xmp, "tiff:Make"))
    if metadata.camera_model is None:
        metadata.camera_model = valid_text(_xmp_value(xmp, "tiff:Model"))


def _parse_xmp_coordinate(raw: str | None) -> float | None:
    """XMP-GPS-Format "DDD,MM.mmk" bzw. "DDD,MM,SSk" mit k in N/S/E/W."""
    if not raw:
        return None
    match = re.match(r"^\s*(\d{1,3}),(\d{1,2}(?:\.\d+)?)(?:,(\d{1,2}(?:\.\d+)?))?\s*([NSEW])\s*$", raw, re.IGNORECASE)
    if not match:
        return None
    degrees, minutes, seconds, ref = match.groups()
    value = float(degrees) + float(minutes) / 60.0 + (float(seconds) / 3600.0 if seconds else 0.0)
    return -value if ref.upper() in ("S", "W") else value


# --- Client-Eingaben ----------------------------------------------------------------------


def metadata_from_client(payload: dict[str, Any] | None) -> ImageMetadata:
    """Client-Metadaten (siehe schemas.files.ClientImageMetadata als dict) -> validierte
    ImageMetadata. Unplausible Einzelwerte werden verworfen, nie korrigiert."""
    metadata = ImageMetadata()
    if not payload:
        return metadata
    raw_taken = payload.get("taken_at")
    if isinstance(raw_taken, datetime):
        metadata.taken_at = valid_capture_datetime(raw_taken.replace(tzinfo=None))
    elif raw_taken:
        metadata.taken_at = parse_exif_datetime(raw_taken)
    if metadata.taken_at is not None:
        metadata.taken_offset = valid_offset(payload.get("taken_offset"))
    gps = payload.get("gps") or {}
    coordinates = valid_coordinates(gps.get("latitude"), gps.get("longitude"))
    if coordinates is not None:
        metadata.gps_latitude, metadata.gps_longitude = coordinates
        metadata.gps_altitude_m = _valid_float(gps.get("altitude_m"), MIN_ALTITUDE_M, MAX_ALTITUDE_M) if gps.get("altitude_m") is not None else None
        metadata.gps_direction_deg = valid_direction(gps.get("direction_deg")) if gps.get("direction_deg") is not None else None
        metadata.gps_accuracy_m = _valid_float(gps.get("accuracy_m"), 0.0, MAX_ACCURACY_M) if gps.get("accuracy_m") is not None else None
        raw_gps_time = gps.get("timestamp")
        if isinstance(raw_gps_time, datetime):
            stamp = valid_capture_datetime(raw_gps_time)
            metadata.gps_timestamp = stamp.replace(tzinfo=UTC) if stamp else None
    metadata.camera_make = valid_text(payload.get("camera_make"))
    metadata.camera_model = valid_text(payload.get("camera_model"))
    metadata.width = valid_dimension(payload.get("width"))
    metadata.height = valid_dimension(payload.get("height"))
    if metadata.width is None or metadata.height is None:
        metadata.width = metadata.height = None
    metadata.orientation = valid_orientation(payload.get("orientation"))
    return metadata


# --- Ergänzen fehlender Werte ---------------------------------------------------------------


def _stored_naive(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo is not None else value


def merge_missing_metadata(
    stored_file: Any,
    incoming: ImageMetadata,
    *,
    source: MetadataSource,
    include_geometry: bool = True,
) -> MergeOutcome:
    """Ergänzt in `stored_file` (StoredFile) nur fehlende Werte aus `incoming`.
    include_geometry=False für Client-Werte zu konvertierten Bildern: Abmessungen und
    Ausrichtung des HEIC-Originals gelten nicht für das gespeicherte, bereits gedrehte JPEG.
    Das geschätzte Datum behandelt apply_estimated_date separat."""
    outcome = MergeOutcome()

    if incoming.taken_at is not None:
        if stored_file.exif_taken_at is None:
            stored_file.exif_taken_at = incoming.taken_at.replace(tzinfo=UTC)
            stored_file.exif_taken_offset = incoming.taken_offset
            stored_file.exif_taken_source = source
            outcome.add_applied(FIELD_TAKEN_AT)
        elif abs(_stored_naive(stored_file.exif_taken_at) - incoming.taken_at) > _TIME_TOLERANCE:
            outcome.add_conflict(FIELD_TAKEN_AT)
        elif stored_file.exif_taken_offset is None and incoming.taken_offset is not None:
            stored_file.exif_taken_offset = incoming.taken_offset
            outcome.add_applied(FIELD_TAKEN_AT)

    if incoming.gps_latitude is not None and incoming.gps_longitude is not None:
        if stored_file.gps_latitude is None:
            stored_file.gps_latitude = incoming.gps_latitude
            stored_file.gps_longitude = incoming.gps_longitude
            stored_file.gps_altitude_m = incoming.gps_altitude_m
            stored_file.gps_direction_deg = incoming.gps_direction_deg
            stored_file.gps_accuracy_m = incoming.gps_accuracy_m
            stored_file.gps_timestamp = incoming.gps_timestamp
            stored_file.gps_source = source
            outcome.add_applied(FIELD_GPS)
        elif (
            abs(stored_file.gps_latitude - incoming.gps_latitude) > _GPS_TOLERANCE_DEG
            or abs(stored_file.gps_longitude - incoming.gps_longitude) > _GPS_TOLERANCE_DEG
        ):
            outcome.add_conflict(FIELD_GPS)
        else:
            # Gleicher Standort: nur fehlende Zusatzangaben auffüllen.
            for attribute in ("gps_altitude_m", "gps_direction_deg", "gps_accuracy_m", "gps_timestamp"):
                if getattr(stored_file, attribute) is None and getattr(incoming, attribute) is not None:
                    setattr(stored_file, attribute, getattr(incoming, attribute))
                    outcome.add_applied(FIELD_GPS)

    for attribute in ("camera_make", "camera_model"):
        value = getattr(incoming, attribute)
        if value is None:
            continue
        current = getattr(stored_file, attribute)
        if current is None:
            setattr(stored_file, attribute, value)
            outcome.add_applied(FIELD_CAMERA)
        elif current.strip().lower() != value.strip().lower():
            outcome.add_conflict(FIELD_CAMERA)

    if include_geometry:
        if incoming.width is not None and incoming.height is not None and stored_file.width is None and stored_file.height is None:
            stored_file.width, stored_file.height = incoming.width, incoming.height
            outcome.add_applied(FIELD_DIMENSIONS)
        if incoming.orientation is not None and stored_file.orientation is None:
            stored_file.orientation = incoming.orientation
            outcome.add_applied(FIELD_ORIENTATION)
    return outcome


def apply_estimated_date(stored_file: Any, estimated: date | None, *, user_id: int | None) -> MergeOutcome:
    """Automatischer Weg (Upload/Hash-Abgleich): setzt ein geschätztes Datum nur, wenn weder
    ein echtes noch bereits ein geschätztes Datum vorhanden ist. Ein abweichendes vorhandenes
    Schätzdatum wird als Konflikt gemeldet und nie überschrieben - bewusste Änderungen laufen
    über PATCH /stored-files/{id}/capture-date (set_estimated_date)."""
    outcome = MergeOutcome()
    estimated = valid_estimated_date(estimated)
    if estimated is None or stored_file.exif_taken_at is not None:
        return outcome
    if stored_file.estimated_taken_on is None:
        stored_file.estimated_taken_on = estimated
        stored_file.estimated_taken_set_at = datetime.now(UTC)
        stored_file.estimated_taken_set_by = user_id
        outcome.add_applied(FIELD_ESTIMATED)
    elif stored_file.estimated_taken_on != estimated:
        outcome.add_conflict(FIELD_ESTIMATED)
    return outcome


def set_estimated_date(stored_file: Any, estimated: date | None, *, user_id: int | None) -> bool:
    """Expliziter Bearbeitungsweg: setzt, ändert oder löscht (None) das Schätzdatum. Das echte
    Aufnahmedatum und das Uploaddatum bleiben unberührt. True, wenn sich etwas geändert hat."""
    if estimated is not None and valid_estimated_date(estimated) is None:
        raise ValueError("Ungültiges geschätztes Aufnahmedatum")
    if stored_file.estimated_taken_on == estimated:
        return False
    stored_file.estimated_taken_on = estimated
    stored_file.estimated_taken_set_at = datetime.now(UTC) if estimated is not None else None
    stored_file.estimated_taken_set_by = user_id if estimated is not None else None
    return True


def apply_server_analysis(stored_file: Any, metadata: ImageMetadata, *, source: MetadataSource = "server") -> MergeOutcome:
    """Ergebnis einer serverseitigen Analyse übernehmen (nur fehlende Werte) und als
    analysiert markieren. Ein hocX-Schätzdatum aus XMP wird ohne Benutzer übernommen."""
    outcome = merge_missing_metadata(stored_file, metadata, source=source)
    if metadata.estimated_taken_on is not None:
        outcome.extend(apply_estimated_date(stored_file, metadata.estimated_taken_on, user_id=None))
    stored_file.metadata_scanned_at = datetime.now(UTC)
    stored_file.metadata_scan_status = metadata.status
    return outcome


def mark_scan_status(stored_file: Any, status: ScanStatus) -> None:
    stored_file.metadata_scanned_at = datetime.now(UTC)
    stored_file.metadata_scan_status = status


def wants_any(stored_file: Any, incoming: ImageMetadata) -> bool:
    """Liefert `incoming` überhaupt etwas, das `stored_file` fehlt? Spart das Lesen der
    Originaldatei, wenn nichts zu ergänzen ist."""
    checks: Iterable[tuple[Any, Any]] = (
        (stored_file.exif_taken_at, incoming.taken_at),
        (stored_file.gps_latitude, incoming.gps_latitude),
        (stored_file.gps_altitude_m, incoming.gps_altitude_m),
        (stored_file.gps_direction_deg, incoming.gps_direction_deg),
        (stored_file.camera_make, incoming.camera_make),
        (stored_file.camera_model, incoming.camera_model),
        (stored_file.width, incoming.width),
        (stored_file.orientation, incoming.orientation),
    )
    return any(current is None and offered is not None for current, offered in checks)
