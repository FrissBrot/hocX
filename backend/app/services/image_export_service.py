"""Export von Bildern mit dem geschätzten Aufnahmedatum in den Bildmetadaten.

Gespeicherte Originale werden nie verändert - diese Funktionen erzeugen nur Bytes für eine
temporäre Kopie (Download, ZIP, Freigabe-Link).

Fälle (siehe backend/UPLOAD_DUPLICATES.md, Abschnitt Export):

A. Echtes Aufnahmedatum vorhanden (StoredFile.exif_taken_at oder DateTimeOriginal in der Datei):
   Datei bleibt, wie sie ist.
B. Nur ein geschätztes Datum: es wird als Aufnahmedatum eingetragen, damit andere Programme
   das Bild richtig einsortieren.
   - XMP: photoshop:DateCreated = "JJJJ-MM-TT" (XMP erlaubt ein reines Datum - keine Uhrzeit
     erfunden) plus hocx:CaptureDateEstimated="True" und hocx:EstimatedCaptureDate.
   - EXIF DateTimeOriginal/DateTimeDigitized verlangen zwingend eine Uhrzeit. Konvention:
     "JJJJ:MM:TT 12:00:00" ohne OffsetTime. Mittag, damit kein Programm das Datum durch eine
     Zeitzonenumrechnung auf den Vor- oder Folgetag schiebt. Der geschätzte Charakter steht
     zusätzlich im EXIF-UserComment (falls dort noch nichts steht) und im XMP oben.
   Lädt man ein so exportiertes Bild wieder in hocX hoch, erkennt image_metadata_service die
   hocX-Markierung und übernimmt das Datum wieder als geschätztes Datum, nicht als echtes.
C. Weder echtes noch geschätztes Datum: es wird kein Datum geschrieben, insbesondere nie das
   Uploaddatum.

Zusätzlich: Liegen GPS-Daten nur in der Datenbank vor (z. B. vom Browser für ein konvertiertes
Bild nachgeliefert), aber nicht in der Datei, werden sie beim Export in das GPS-IFD geschrieben.
Vorhandene EXIF-Werte (inkl. GPS) bleiben erhalten.

Unterstützt: JPEG, PNG, WebP (verlustfrei auf Segment-/Chunk-Ebene, kein Re-Encode). TIFF,
GIF, BMP und alles andere wird unverändert exportiert (Einschränkung, dokumentiert).
"""

from __future__ import annotations

import io
import logging
import re
import struct
import zlib
from datetime import date
from fractions import Fraction
from typing import Any

from PIL import Image
from PIL.TiffImagePlugin import IFDRational

from app.services.image_metadata_service import HOCX_XMP_NAMESPACE, parse_exif_datetime

logger = logging.getLogger(__name__)

EXPORTABLE_MIME_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})

_EXIF_IFD = 0x8769
_GPS_IFD = 0x8825
_DATETIME_ORIGINAL = 0x9003
_DATETIME_DIGITIZED = 0x9004
_OFFSET_TAGS = (0x9010, 0x9011, 0x9012)
_USER_COMMENT = 0x9286
ESTIMATED_TIME_CONVENTION = "12:00:00"
_USER_COMMENT_TEXT = "hocX: geschaetztes Aufnahmedatum, nur der Tag ist bekannt (Uhrzeit 12:00 technisch gesetzt)"
_XMP_JPEG_HEADER = b"http://ns.adobe.com/xap/1.0/\x00"


# --- Entscheidung -------------------------------------------------------------------------


def _wants_date(stored_file: Any) -> date | None:
    if stored_file.exif_taken_at is not None:
        return None
    return stored_file.estimated_taken_on


def _wants_gps(stored_file: Any) -> bool:
    return stored_file.gps_latitude is not None and stored_file.gps_longitude is not None


def needs_export_processing(stored_file: Any) -> bool:
    """Billige Vorprüfung ohne Dateizugriff: kommt eine Änderung überhaupt in Frage?"""
    return stored_file.mime_type in EXPORTABLE_MIME_TYPES and (_wants_date(stored_file) is not None or _wants_gps(stored_file))


def export_bytes(stored_file: Any, original: bytes) -> bytes | None:
    """Exportfassung von `original` oder None, wenn das Original unverändert passt. Fehler beim
    Umschreiben führen nie zu einem fehlgeschlagenen Download: dann geht das Original raus."""
    if not needs_export_processing(stored_file):
        return None
    try:
        return _export(stored_file, original)
    except Exception:
        logger.warning("Exportmetadaten konnten nicht geschrieben werden (%s) - Original wird geliefert", stored_file.mime_type, exc_info=True)
        return None


def _export(stored_file: Any, original: bytes) -> bytes | None:
    mime = stored_file.mime_type
    if mime == "image/jpeg":
        exif_bytes, xmp = _jpeg_metadata(original)
    elif mime == "image/png":
        exif_bytes, xmp = _png_metadata(original)
    else:
        exif_bytes, xmp = _webp_metadata(original)

    estimated = _wants_date(stored_file)
    new_exif = _updated_exif(exif_bytes, stored_file, estimated)
    if new_exif is None:
        return None
    date_written = estimated is not None and new_exif[1]
    new_xmp = _updated_xmp(xmp, estimated) if date_written else None
    if mime == "image/jpeg":
        return _write_jpeg(original, new_exif[0], new_xmp)
    if mime == "image/png":
        return _write_png(original, new_exif[0], new_xmp)
    return _write_webp(original, new_exif[0], new_xmp)


def _to_rational(value: float, precision: int = 1_000_000) -> IFDRational:
    fraction = Fraction(value).limit_denominator(precision)
    return IFDRational(fraction.numerator, fraction.denominator)


def _degrees_to_dms(value: float) -> tuple[IFDRational, IFDRational, IFDRational]:
    value = abs(value)
    degrees = int(value)
    minutes_full = (value - degrees) * 60
    minutes = int(minutes_full)
    seconds = (minutes_full - minutes) * 60
    return IFDRational(degrees, 1), IFDRational(minutes, 1), _to_rational(round(seconds, 4), 10_000)


def _gps_ifd(stored_file: Any) -> dict[int, Any]:
    gps: dict[int, Any] = {
        0: b"\x02\x03\x00\x00",
        1: "S" if stored_file.gps_latitude < 0 else "N",
        2: _degrees_to_dms(stored_file.gps_latitude),
        3: "W" if stored_file.gps_longitude < 0 else "E",
        4: _degrees_to_dms(stored_file.gps_longitude),
    }
    if stored_file.gps_altitude_m is not None:
        gps[5] = b"\x01" if stored_file.gps_altitude_m < 0 else b"\x00"
        gps[6] = _to_rational(abs(stored_file.gps_altitude_m), 1000)
    if stored_file.gps_direction_deg is not None:
        gps[16] = "T"
        gps[17] = _to_rational(stored_file.gps_direction_deg, 1000)
    return gps


def _updated_exif(exif_bytes: bytes | None, stored_file: Any, estimated: date | None) -> tuple[bytes, bool] | None:
    """(neuer EXIF-Block mit "Exif\\0\\0"-Präfix, Datum geschrieben?) oder None, wenn nichts
    zu ändern ist. Ein in der Datei vorhandenes echtes Aufnahmedatum gewinnt immer."""
    exif = Image.Exif()
    if exif_bytes:
        exif.load(exif_bytes)
    exif_ifd = dict(exif.get_ifd(_EXIF_IFD)) if _EXIF_IFD in exif else {}
    changed = False
    date_written = False
    if estimated is not None and parse_exif_datetime(exif_ifd.get(_DATETIME_ORIGINAL)) is None:
        stamp = f"{estimated:%Y:%m:%d} {ESTIMATED_TIME_CONVENTION}"
        exif_ifd[_DATETIME_ORIGINAL] = stamp
        exif_ifd[_DATETIME_DIGITIZED] = stamp
        for tag in _OFFSET_TAGS:
            exif_ifd.pop(tag, None)
        if _USER_COMMENT not in exif_ifd:
            exif_ifd[_USER_COMMENT] = b"ASCII\x00\x00\x00" + _USER_COMMENT_TEXT.encode("ascii")
        changed = date_written = True
    has_gps = _GPS_IFD in exif and bool(exif.get_ifd(_GPS_IFD).get(2))
    if _wants_gps(stored_file) and not has_gps:
        exif[_GPS_IFD] = _gps_ifd(stored_file)
        changed = True
    if not changed:
        return None
    if _EXIF_IFD in exif:
        del exif[_EXIF_IFD]
    if exif_ifd:
        exif[_EXIF_IFD] = exif_ifd
    return exif.tobytes(), date_written


def _updated_xmp(xmp: bytes | None, estimated: date) -> bytes | None:
    """Neues XMP-Paket bzw. vorhandenes mit ergänzten Attributen. None, wenn das vorhandene
    XMP schon ein Erstellungsdatum hat oder sich nicht sicher ergänzen lässt."""
    iso = estimated.isoformat()
    attributes = (
        f' xmlns:photoshop="http://ns.adobe.com/photoshop/1.0/" xmlns:hocx="{HOCX_XMP_NAMESPACE}"'
        f' photoshop:DateCreated="{iso}" hocx:CaptureDateEstimated="True" hocx:EstimatedCaptureDate="{iso}"'
    )
    if xmp is None:
        packet = (
            '<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>'
            '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
            f'<rdf:Description rdf:about=""{attributes}/>'
            '</rdf:RDF></x:xmpmeta><?xpacket end="w"?>'
        )
        return packet.encode("utf-8")
    text = xmp.decode("utf-8", "ignore")
    if "photoshop:DateCreated" in text or "xmlns:photoshop" in text or "xmlns:hocx" in text:
        return None
    match = re.search(r"<rdf:Description\b", text)
    if match is None:
        return None
    return (text[: match.end()] + attributes + text[match.end() :]).encode("utf-8")


# --- JPEG ---------------------------------------------------------------------------------


def _jpeg_segments(data: bytes) -> tuple[list[tuple[int, bytes]], int]:
    """Segmente vor SOS als (Marker, komplettes Segment) und Offset des SOS."""
    if data[:2] != b"\xff\xd8":
        raise ValueError("kein JPEG")
    segments: list[tuple[int, bytes]] = []
    pos = 2
    while pos + 4 <= len(data):
        if data[pos] != 0xFF:
            raise ValueError("defektes JPEG-Segment")
        marker = data[pos + 1]
        if marker == 0xFF:
            pos += 1
            continue
        if marker == 0xDA:  # SOS: Bilddaten folgen, Rest unverändert übernehmen
            return segments, pos
        (length,) = struct.unpack(">H", data[pos + 2 : pos + 4])
        segments.append((marker, data[pos : pos + 2 + length]))
        pos += 2 + length
    raise ValueError("JPEG ohne SOS")


def _jpeg_metadata(data: bytes) -> tuple[bytes | None, bytes | None]:
    segments, _ = _jpeg_segments(data)
    exif = xmp = None
    for marker, segment in segments:
        payload = segment[4:]
        if marker == 0xE1 and payload.startswith(b"Exif\x00\x00") and exif is None:
            exif = payload
        elif marker == 0xE1 and payload.startswith(_XMP_JPEG_HEADER) and xmp is None:
            xmp = payload[len(_XMP_JPEG_HEADER) :]
    return exif, xmp


def _app1(payload: bytes) -> bytes:
    if len(payload) + 2 > 0xFFFF:
        raise ValueError("Metadatenblock zu gross für ein JPEG-Segment")
    return b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload


def _write_jpeg(data: bytes, exif: bytes, xmp: bytes | None) -> bytes:
    """Neuer EXIF-Block (und ggf. XMP) direkt nach SOI bzw. JFIF; alle anderen Segmente und
    die Bilddaten (inkl. angehängter MPF-Zusatzbilder) bleiben byte-gleich."""
    segments, sos = _jpeg_segments(data)
    out = bytearray(b"\xff\xd8")
    rest = list(segments)
    if rest and rest[0][0] == 0xE0:
        out += rest.pop(0)[1]
    out += _app1(exif)
    if xmp is not None:
        out += _app1(_XMP_JPEG_HEADER + xmp)
    for marker, segment in rest:
        payload = segment[4:]
        if marker == 0xE1 and payload.startswith(b"Exif\x00\x00"):
            continue
        if marker == 0xE1 and payload.startswith(_XMP_JPEG_HEADER) and xmp is not None:
            continue
        out += segment
    out += data[sos:]
    return bytes(out)


# --- PNG ----------------------------------------------------------------------------------

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_PNG_XMP_KEYWORD = b"XML:com.adobe.xmp"
# Obergrenze für entpacktes PNG-XMP: Deflate erreicht ~1000:1, ein präpariertes iTXt könnte
# sonst aus wenigen MB mehrere GB machen (Download/Freigabe-Links). Echte XMP-Pakete sind
# selbst mit Bearbeitungshistorie deutlich kleiner.
MAX_PNG_XMP_BYTES = 2 * 1024 * 1024


def _png_chunks(data: bytes) -> list[tuple[bytes, bytes]]:
    if not data.startswith(_PNG_SIGNATURE):
        raise ValueError("kein PNG")
    chunks = []
    pos = len(_PNG_SIGNATURE)
    while pos + 8 <= len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        kind = data[pos + 4 : pos + 8]
        chunks.append((kind, data[pos + 8 : pos + 8 + length]))
        pos += 12 + length
        if kind == b"IEND":
            return chunks
    raise ValueError("PNG ohne IEND")


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)


def _is_png_xmp(payload: bytes) -> bool:
    return payload.partition(b"\x00")[0] == _PNG_XMP_KEYWORD


def _png_xmp(payload: bytes) -> bytes | None:
    keyword, _, rest = payload.partition(b"\x00")
    if keyword != _PNG_XMP_KEYWORD or len(rest) < 4:
        return None
    compressed, _method = rest[0], rest[1]
    text = rest[2:].split(b"\x00", 2)
    if len(text) < 3:
        return None
    body = text[2]
    if not compressed:
        return body
    # Begrenzt entpacken; zu grosses XMP bricht den Export ab (export_bytes liefert dann das
    # unveränderte Original) statt den Worker-Speicher zu sprengen.
    inflater = zlib.decompressobj()
    xmp = inflater.decompress(body, MAX_PNG_XMP_BYTES + 1)
    if len(xmp) > MAX_PNG_XMP_BYTES or inflater.unconsumed_tail:
        raise ValueError("PNG-XMP überschreitet die Entpackgrenze")
    return xmp


def _png_metadata(data: bytes) -> tuple[bytes | None, bytes | None]:
    exif = xmp = None
    for kind, payload in _png_chunks(data):
        if kind == b"eXIf" and exif is None:
            exif = b"Exif\x00\x00" + payload
        elif kind == b"iTXt" and xmp is None:
            xmp = _png_xmp(payload)
    return exif, xmp


def _write_png(data: bytes, exif: bytes, xmp: bytes | None) -> bytes:
    out = bytearray(_PNG_SIGNATURE)
    inserted = False
    for kind, payload in _png_chunks(data):
        if kind == b"eXIf":
            continue
        if kind == b"iTXt" and xmp is not None and _is_png_xmp(payload):
            continue
        if not inserted and kind in (b"IDAT", b"IEND"):
            out += _png_chunk(b"eXIf", exif.removeprefix(b"Exif\x00\x00"))
            if xmp is not None:
                out += _png_chunk(b"iTXt", b"XML:com.adobe.xmp\x00\x00\x00\x00\x00" + xmp)
            inserted = True
        out += _png_chunk(kind, payload)
    return bytes(out)


# --- WebP ---------------------------------------------------------------------------------

_VP8X_EXIF_FLAG = 0x08
_VP8X_XMP_FLAG = 0x04


def _webp_chunks(data: bytes) -> list[tuple[bytes, bytes]]:
    if data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        raise ValueError("kein WebP")
    chunks = []
    pos = 12
    while pos + 8 <= len(data):
        kind = data[pos : pos + 4]
        (length,) = struct.unpack("<I", data[pos + 4 : pos + 8])
        chunks.append((kind, data[pos + 8 : pos + 8 + length]))
        pos += 8 + length + (length & 1)
    return chunks


def _webp_metadata(data: bytes) -> tuple[bytes | None, bytes | None]:
    exif = xmp = None
    for kind, payload in _webp_chunks(data):
        if kind == b"EXIF" and exif is None:
            exif = payload if payload.startswith(b"Exif\x00\x00") else b"Exif\x00\x00" + payload
        elif kind == b"XMP " and xmp is None:
            xmp = payload
    return exif, xmp


def _write_webp(data: bytes, exif: bytes, xmp: bytes | None) -> bytes:
    chunks = [(kind, payload) for kind, payload in _webp_chunks(data) if kind != b"EXIF" and not (kind == b"XMP " and xmp is not None)]
    if not any(kind == b"VP8X" for kind, _ in chunks):
        # Einfaches WebP (nur VP8/VP8L) kennt keine Metadaten-Chunks: erweitertes Format mit
        # VP8X-Kopf anlegen; Canvasgrösse = Bildgrösse.
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            alpha = 0x10 if image.mode in ("RGBA", "LA") else 0
        vp8x = bytes([alpha, 0, 0, 0]) + (width - 1).to_bytes(3, "little") + (height - 1).to_bytes(3, "little")
        chunks.insert(0, (b"VP8X", vp8x))
    chunks.append((b"EXIF", exif.removeprefix(b"Exif\x00\x00")))
    has_xmp = any(kind == b"XMP " for kind, _ in chunks)
    if xmp is not None:
        chunks.append((b"XMP ", xmp))
        has_xmp = True
    body = bytearray(b"WEBP")
    for kind, payload in chunks:
        if kind == b"VP8X":
            flags = payload[0] | _VP8X_EXIF_FLAG
            flags = flags | _VP8X_XMP_FLAG if has_xmp else flags & ~_VP8X_XMP_FLAG
            payload = bytes([flags]) + payload[1:]
        body += kind + struct.pack("<I", len(payload)) + payload
        if len(payload) & 1:
            body += b"\x00"
    return b"RIFF" + struct.pack("<I", len(body)) + bytes(body)
