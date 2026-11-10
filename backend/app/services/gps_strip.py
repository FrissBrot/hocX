"""GPS beim Upload weglassen (Datenschutz-Audit Paket 9.3: Option «GPS-Daten des Bildes mitsenden»).

Entfernt nur Standortangaben und lässt alles andere unverändert (Aufnahmedatum, Kamera, Bilddaten):

- EXIF (JPEG, HEIC/HEIF, WebP, PNG, TIFF): das GPS-IFD wird mit Nullen überschrieben und auf
  0 Einträge gesetzt - samt der Werte, auf die es zeigt.
- XMP: Attribute und Elemente ``exif:GPS…`` bekommen Leerzeichen statt Werten.
- Videos (MOV/MP4, Live-Photo-Clips): ISO-6709-Ortsangaben (``©xyz``, QuickTime-Location) werden
  mit Leerzeichen überschrieben.

Alles geschieht an Ort und Stelle mit gleicher Länge, damit Container-Offsets (HEIC ``iloc``,
MP4-Atome) gültig bleiben - es wird nichts neu kodiert. PNG-Chunks bekommen eine neue CRC.

Bewusst ohne Abhängigkeiten (nur Standardbibliothek): wird per scripts/sync-objstore-client.sh in
die Abgabebox kopiert, die keinen Backend-Code importieren darf.
"""
from __future__ import annotations

import re
import struct
import zlib

_EXIF_MARK = b"Exif\x00\x00"
_TIFF_HEADERS = (b"II*\x00", b"MM\x00*")
_GPS_IFD_TAG = 0x8825
_TYPE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8, 13: 4}
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# Grenzen gegen manipulierte Dateien (öffentlich erreichbar über die Abgabebox): echte Kameras
# schreiben wenige Dutzend IFD-Einträge und eine Handvoll EXIF-Blöcke (Hauptbild, MPF-Vorschauen).
_MAX_IFD_ENTRIES = 512
_MAX_EXIF_BLOCKS = 16

_XMP_ATTRIBUTE = re.compile(rb'(exif:GPS[A-Za-z]*\s*=\s*")([^"]*)(")')
_XMP_ELEMENT = re.compile(rb"(<exif:GPS[A-Za-z]*>)([^<]*)(</exif:GPS[A-Za-z]*>)")
# ISO 6709, wie Kameras und iPhones es in MOV/MP4 schreiben: +47.3769+008.5417+408.000/
_ISO6709 = re.compile(rb"[+-]\d{1,2}(?:\.\d+)?[+-]\d{1,3}(?:\.\d+)?(?:[+-]\d+(?:\.\d+)?)?(?:CRS[A-Za-z0-9_:]*)?/")

VIDEO_MIME_TYPES = frozenset({"video/mp4", "video/quicktime"})


def _blank(buffer: bytearray, start: int, length: int, fill: int = 0) -> None:
    buffer[start:start + length] = bytes([fill]) * length


def _blank_gps_ifd(buffer: bytearray, base: int, end: int, endian: str, offset: int) -> bool:
    entries_at = base + offset
    if offset <= 0 or entries_at + 2 > end:
        return False
    (count,) = struct.unpack_from(endian + "H", buffer, entries_at)
    if count == 0 or count > _MAX_IFD_ENTRIES or entries_at + 2 + 12 * count > end:
        return False
    for index in range(count):
        entry = entries_at + 2 + 12 * index
        field_type, items = struct.unpack_from(endian + "HI", buffer, entry + 2)
        size = _TYPE_SIZES.get(field_type, 1) * items
        if size > 4:
            (value_offset,) = struct.unpack_from(endian + "I", buffer, entry + 8)
            if 0 < value_offset and base + value_offset + size <= end:
                _blank(buffer, base + value_offset, size)
        _blank(buffer, entry, 12)
    # Keine Einträge mehr; der Zeiger auf ein Folge-IFD liegt danach in den genullten Bytes (= keins).
    struct.pack_into(endian + "H", buffer, entries_at, 0)
    return True


def _blank_tiff(buffer: bytearray, base: int, end: int) -> bool:
    """TIFF-Block ab ``base`` (Byte-Order-Marke): GPS-IFD aus IFD0 leeren."""
    if base + 8 > end or bytes(buffer[base:base + 4]) not in _TIFF_HEADERS:
        return False
    endian = "<" if buffer[base:base + 2] == b"II" else ">"
    (ifd0,) = struct.unpack_from(endian + "I", buffer, base + 4)
    if ifd0 < 8 or base + ifd0 + 2 > end:
        return False
    (count,) = struct.unpack_from(endian + "H", buffer, base + ifd0)
    if count > _MAX_IFD_ENTRIES or base + ifd0 + 2 + 12 * count > end:
        return False
    changed = False
    for index in range(count):
        entry = base + ifd0 + 2 + 12 * index
        (tag,) = struct.unpack_from(endian + "H", buffer, entry)
        if tag == _GPS_IFD_TAG:
            (gps_offset,) = struct.unpack_from(endian + "I", buffer, entry + 8)
            changed = _blank_gps_ifd(buffer, base, end, endian, gps_offset) or changed
    return changed


def _blank_exif_blocks(buffer: bytearray, start: int = 0, end: int | None = None) -> bool:
    end = len(buffer) if end is None else end
    changed = False
    blocks = 0
    position = buffer.find(_EXIF_MARK, start, end)
    while position != -1 and blocks < _MAX_EXIF_BLOCKS:
        if _blank_tiff(buffer, position + len(_EXIF_MARK), end):
            changed = True
            blocks += 1
        position = buffer.find(_EXIF_MARK, position + 1, end)
    return changed


def _scrub_text(buffer: bytearray, start: int = 0, end: int | None = None, *, video: bool = False) -> bool:
    end = len(buffer) if end is None else end
    # Ohne Kopie suchen (Videos können gross sein); ersetzt wird nur mit gleicher Länge.
    segment = memoryview(buffer)[start:end]
    changed = False
    patterns = [(_XMP_ATTRIBUTE, 2), (_XMP_ELEMENT, 2)] + ([(_ISO6709, 0)] if video else [])
    for pattern, group in patterns:
        for match in pattern.finditer(segment):
            begin, finish = match.span(group)
            if finish > begin:
                _blank(buffer, start + begin, finish - begin, fill=0x20)
                changed = True
    return changed


def _strip_png(buffer: bytearray) -> bool:
    changed = False
    position = len(_PNG_SIGNATURE)
    while position + 12 <= len(buffer):
        (length,) = struct.unpack_from(">I", buffer, position)
        kind = bytes(buffer[position + 4:position + 8])
        data_start, data_end = position + 8, position + 8 + length
        if data_end + 4 > len(buffer):
            break
        touched = False
        if kind == b"eXIf":
            touched = _blank_tiff(buffer, data_start, data_end)
        elif kind in (b"iTXt", b"tEXt", b"zTXt"):
            touched = _scrub_text(buffer, data_start, data_end)
        if touched:
            struct.pack_into(">I", buffer, data_end, zlib.crc32(bytes(buffer[position + 4:data_end])) & 0xFFFFFFFF)
            changed = True
        if kind == b"IEND":
            break
        position = data_end + 4
    return changed


def _strip_webp(buffer: bytearray) -> bool:
    changed = False
    position = 12
    while position + 8 <= len(buffer):
        kind = bytes(buffer[position:position + 4])
        (length,) = struct.unpack_from("<I", buffer, position + 4)
        data_start, data_end = position + 8, min(position + 8 + length, len(buffer))
        if kind == b"EXIF":
            body = data_start + (len(_EXIF_MARK) if buffer[data_start:data_start + 6] == _EXIF_MARK else 0)
            changed = _blank_tiff(buffer, body, data_end) or changed
        elif kind == b"XMP ":
            changed = _scrub_text(buffer, data_start, data_end) or changed
        position = data_end + (length & 1)
    return changed


def strip_gps(data: bytes, mime_type: str | None = None) -> bytes:
    """Kopie von ``data`` ohne Standortangaben, sonst unverändert (gleiche Länge)."""
    buffer = bytearray(data)
    if buffer.startswith(_PNG_SIGNATURE):
        _strip_png(buffer)
        return bytes(buffer)
    if buffer[:4] == b"RIFF" and buffer[8:12] == b"WEBP":
        _strip_webp(buffer)
        return bytes(buffer)
    if bytes(buffer[:4]) in _TIFF_HEADERS:
        _blank_tiff(buffer, 0, len(buffer))
    # JPEG (APP1, auch MPF-Zusatzbilder) und HEIC/HEIF (Exif-Item mit "Exif\0\0"-Kopf)
    _blank_exif_blocks(buffer)
    _scrub_text(buffer, video=(mime_type or "") in VIDEO_MIME_TYPES)
    return bytes(buffer)
