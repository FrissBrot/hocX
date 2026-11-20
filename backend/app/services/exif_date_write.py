"""Korrigiertes Aufnahmedatum in die Bilddatei schreiben und wieder zurücknehmen (Migration 0203).

Gegenstück zu gps_strip.py: die Datumsfelder werden an Ort und Stelle mit gleicher Länge
überschrieben - nichts wird neu kodiert, Container-Offsets (HEIC ``iloc``, MPF, WebP-RIFF) bleiben
gültig, PNG-Chunks bekommen eine neue CRC. Geschrieben werden ``DateTimeOriginal`` (0x9003),
``DateTimeDigitized`` (0x9004) und ``DateTime`` (0x0132), soweit vorhanden, in allen EXIF-Blöcken,
die auch gps_strip findet (JPEG inkl. MPF-Zusatzbilder, HEIC/HEIF mit und ohne "Exif\\0\\0",
WebP, PNG, TIFF). ``OffsetTime*`` bleibt unverändert.

Drei Arten, wie eine Datei das Datum bekommt - jede mit einem eigenen Rückweg, beschrieben im
Original-Datensatz (``stored_file.capture_exif_original``, JSON, nur beim ERSTEN Schreiben):

- ``inplace``: Die Datei hat ein ``DateTimeOriginal``. Gespeichert werden die ursprünglichen
  Rohbytes jedes überschriebenen Felds (Block-Nummer in Fundreihenfolge + Tag). Wiederherstellen
  schreibt genau diese Bytes zurück (byte-identische Datumsfelder).
- ``inserted``: JPEG ganz ohne EXIF-Block - ein minimales APP1-Exif-Segment (nur
  DateTimeOriginal/DateTimeDigitized) wird nach SOI bzw. JFIF eingefügt. Wiederherstellen
  entfernt es wieder (Datei danach byte-identisch zum Original).
- ``replaced``: JPEG mit EXIF-Block, aber ohne ``DateTimeOriginal`` (z. B. Scans, bearbeitete
  Bilder). Ein zweiter EXIF-Block würde von Lesern ignoriert, darum wird der vorhandene mit PIL
  um die Datumsfelder ergänzt; das komplette ursprüngliche Segment (höchstens 64 KB) wird
  gespeichert und beim Wiederherstellen unverändert zurückgesetzt.

Alles andere (PNG/WebP/HEIC/TIFF ohne ``DateTimeOriginal``, GIF, BMP, defekte Dateien) ist
``ExifDateUnsupported``: die Datei bleibt unverändert, die Korrektur gilt nur in hocX.

Spätere Korrekturen finden das Datum dann immer über ``inplace`` (auch im eingefügten bzw.
ersetzten Block) und speichern kein zweites Original.

Robust gegen manipulierte Dateien: gleiche Grenzen wie gps_strip, jede Stelle wird vor dem
Schreiben auf Länge und Lage geprüft; nach aussen gehen nur ``ExifDateError`` und
``ExifDateUnsupported`` (beide ``ValueError``).
"""

from __future__ import annotations

import base64
import binascii
import re
import struct
import zlib
from dataclasses import dataclass
from typing import Any

from app.services.gps_strip import (
    _EXIF_MARK,
    _MAX_EXIF_BLOCKS,
    _MAX_HEIF_TIFF_CANDIDATES,
    _MAX_IFD_ENTRIES,
    _PNG_SIGNATURE,
    _TIFF_HEADERS,
    _heif_offset_points_to,
    _is_heif,
)

TAG_DATETIME = 0x0132
TAG_DATETIME_ORIGINAL = 0x9003
TAG_DATETIME_DIGITIZED = 0x9004
_EXIF_IFD_TAG = 0x8769
_DATE_TAGS = frozenset({TAG_DATETIME, TAG_DATETIME_ORIGINAL, TAG_DATETIME_DIGITIZED})
_ASCII = 2
# "JJJJ:MM:TT HH:MM:SS\0" = 20 Byte. Längere Felder (manche Software) werden mit NUL aufgefüllt;
# mehr als 64 Byte sind kein Datum, sondern Unfug - solche Felder werden nicht angefasst.
_STAMP_LENGTH = 20
_MAX_SLOT_LENGTH = 64
_STAMP = re.compile(r"^\d{4}:\d{2}:\d{2} \d{2}:\d{2}:\d{2}$")
_ORIGINAL_VERSION = 1
_MAX_JPEG_SEGMENT = 0xFFFF


class ExifDateError(ValueError):
    """Datei oder Original-Datensatz passt nicht (manipuliert, beschädigt, unerwartet verändert)."""


class ExifDateUnsupported(ValueError):
    """Dieses Format/diese Datei kann kein Aufnahmedatum aufnehmen - Datei bleibt unverändert."""


@dataclass(frozen=True)
class _Block:
    base: int  # Byte-Order-Marke des TIFF-Kopfs
    end: int
    png_chunk: int | None = None  # Start des eXIf-Chunks (CRC neu berechnen)


@dataclass(frozen=True)
class _Slot:
    block: int
    tag: int
    offset: int  # absolute Position des Werts in der Datei
    length: int


# --- EXIF-Blöcke und Datumsfelder finden --------------------------------------------------


def _valid_tiff(buffer: bytes | bytearray, base: int, end: int) -> bool:
    return base >= 0 and base + 8 <= end and bytes(buffer[base:base + 4]) in _TIFF_HEADERS


def _png_blocks(buffer: bytearray) -> list[_Block]:
    blocks: list[_Block] = []
    position = len(_PNG_SIGNATURE)
    while position + 12 <= len(buffer) and len(blocks) < _MAX_EXIF_BLOCKS:
        (length,) = struct.unpack_from(">I", buffer, position)
        kind = bytes(buffer[position + 4:position + 8])
        data_start, data_end = position + 8, position + 8 + length
        if data_end + 4 > len(buffer):
            break
        if kind == b"eXIf":
            body = data_start + (len(_EXIF_MARK) if buffer[data_start:data_start + 6] == _EXIF_MARK else 0)
            if _valid_tiff(buffer, body, data_end):
                blocks.append(_Block(body, data_end, png_chunk=position))
        if kind == b"IEND":
            break
        position = data_end + 4
    return blocks


def _webp_blocks(buffer: bytearray) -> list[_Block]:
    blocks: list[_Block] = []
    position = 12
    while position + 8 <= len(buffer) and len(blocks) < _MAX_EXIF_BLOCKS:
        kind = bytes(buffer[position:position + 4])
        (length,) = struct.unpack_from("<I", buffer, position + 4)
        data_start, data_end = position + 8, min(position + 8 + length, len(buffer))
        if kind == b"EXIF":
            body = data_start + (len(_EXIF_MARK) if buffer[data_start:data_start + 6] == _EXIF_MARK else 0)
            if _valid_tiff(buffer, body, data_end):
                blocks.append(_Block(body, data_end))
        position = data_end + (length & 1)
    return blocks


def _marker_blocks(buffer: bytearray) -> list[_Block]:
    """JPEG (APP1, auch MPF-Zusatzbilder), HEIF mit "Exif\\0\\0" und - nur HEIF - Exif-Items ohne."""
    bases: set[int] = set()
    position = buffer.find(_EXIF_MARK)
    while position != -1 and len(bases) < _MAX_EXIF_BLOCKS:
        base = position + len(_EXIF_MARK)
        if _valid_tiff(buffer, base, len(buffer)):
            bases.add(base)
        position = buffer.find(_EXIF_MARK, position + 1)
    if _is_heif(buffer):
        candidates = 0
        for header in _TIFF_HEADERS:
            position = buffer.find(header)
            while position != -1 and candidates < _MAX_HEIF_TIFF_CANDIDATES and len(bases) < _MAX_EXIF_BLOCKS:
                candidates += 1
                if _heif_offset_points_to(buffer, position) and _valid_tiff(buffer, position, len(buffer)):
                    bases.add(position)
                position = buffer.find(header, position + 1)
    return [_Block(base, len(buffer)) for base in sorted(bases)]


def _find_blocks(buffer: bytearray) -> list[_Block]:
    if buffer.startswith(_PNG_SIGNATURE):
        return _png_blocks(buffer)
    if buffer[:4] == b"RIFF" and buffer[8:12] == b"WEBP":
        return _webp_blocks(buffer)
    if bytes(buffer[:4]) in _TIFF_HEADERS:
        return [_Block(0, len(buffer))]
    return _marker_blocks(buffer)


def _ifd_entries(buffer: bytearray, block: _Block, endian: str, offset: int) -> list[tuple[int, int, int, int]]:
    """(tag, typ, anzahl, wert/offset) aller Einträge eines IFD - leer bei ungültiger Lage."""
    start = block.base + offset
    if offset < 8 or start + 2 > block.end:
        return []
    (count,) = struct.unpack_from(endian + "H", buffer, start)
    if count > _MAX_IFD_ENTRIES or start + 2 + 12 * count > block.end:
        return []
    entries = []
    for index in range(count):
        entries.append(struct.unpack_from(endian + "HHII", buffer, start + 2 + 12 * index))
    return entries


def _block_slots(buffer: bytearray, index: int, block: _Block) -> list[_Slot]:
    endian = "<" if buffer[block.base:block.base + 2] == b"II" else ">"
    (ifd0,) = struct.unpack_from(endian + "I", buffer, block.base + 4)
    slots: list[_Slot] = []
    seen: set[int] = set()

    def add(tag: int, field_type: int, count: int, value: int) -> None:
        if tag in seen or field_type != _ASCII or not _STAMP_LENGTH <= count <= _MAX_SLOT_LENGTH:
            return
        if value < 8 or block.base + value + count > block.end:
            return
        seen.add(tag)
        slots.append(_Slot(index, tag, block.base + value, count))

    exif_ifd = None
    for tag, field_type, count, value in _ifd_entries(buffer, block, endian, ifd0):
        if tag == TAG_DATETIME:
            add(tag, field_type, count, value)
        elif tag == _EXIF_IFD_TAG and exif_ifd is None:
            exif_ifd = value
    if exif_ifd is not None:
        for tag, field_type, count, value in _ifd_entries(buffer, block, endian, exif_ifd):
            if tag in (TAG_DATETIME_ORIGINAL, TAG_DATETIME_DIGITIZED):
                add(tag, field_type, count, value)
    return slots


def _find_slots(buffer: bytearray) -> tuple[list[_Block], list[_Slot]]:
    blocks = _find_blocks(buffer)
    slots: list[_Slot] = []
    for index, block in enumerate(blocks):
        slots.extend(_block_slots(buffer, index, block))
    return blocks, slots


def _overlapping(slots: list[_Slot]) -> bool:
    ordered = sorted(slots, key=lambda slot: slot.offset)
    return any(current.offset < previous.offset + previous.length for previous, current in zip(ordered, ordered[1:]))


def _fix_png_crcs(buffer: bytearray, blocks: list[_Block], touched: set[int]) -> None:
    for index in touched:
        chunk = blocks[index].png_chunk
        if chunk is None:
            continue
        (length,) = struct.unpack_from(">I", buffer, chunk)
        data_end = chunk + 8 + length
        struct.pack_into(">I", buffer, data_end, zlib.crc32(bytes(buffer[chunk + 4:data_end])) & 0xFFFFFFFF)


# --- JPEG-Segmente ------------------------------------------------------------------------


def _jpeg_segments(data: bytes) -> list[tuple[int, int, int]]:
    """(Marker, Start, Ende) aller Segmente vor SOS; ExifDateUnsupported bei defektem JPEG."""
    if data[:2] != b"\xff\xd8":
        raise ExifDateUnsupported("kein JPEG")
    segments: list[tuple[int, int, int]] = []
    position = 2
    while position + 4 <= len(data):
        if data[position] != 0xFF:
            raise ExifDateUnsupported("defektes JPEG-Segment")
        marker = data[position + 1]
        if marker == 0xFF:
            position += 1
            continue
        if marker == 0xDA:
            return segments
        (length,) = struct.unpack_from(">H", data, position + 2)
        if length < 2 or position + 2 + length > len(data):
            raise ExifDateUnsupported("defektes JPEG-Segment")
        segments.append((marker, position, position + 2 + length))
        position += 2 + length
    raise ExifDateUnsupported("JPEG ohne SOS")


def _first_exif_segment(data: bytes) -> tuple[int, int] | None:
    for marker, start, end in _jpeg_segments(data):
        if marker == 0xE1 and data[start + 4:start + 10] == _EXIF_MARK:
            return start, end
    return None


def _app1(payload: bytes) -> bytes:
    if len(payload) + 2 > _MAX_JPEG_SEGMENT:
        raise ExifDateUnsupported("EXIF-Block zu gross für ein JPEG-Segment")
    return b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload


def _minimal_exif_segment(stamp: str) -> bytes:
    """APP1 mit IFD0 (nur Zeiger aufs Exif-IFD) und Exif-IFD (DateTimeOriginal, DateTimeDigitized)."""
    value = stamp.encode("ascii") + b"\x00"
    exif_ifd_at = 8 + 2 + 12 + 4
    values_at = exif_ifd_at + 2 + 2 * 12 + 4
    tiff = bytearray(b"II*\x00" + struct.pack("<I", 8))
    tiff += struct.pack("<H", 1) + struct.pack("<HHII", _EXIF_IFD_TAG, 4, 1, exif_ifd_at) + struct.pack("<I", 0)
    tiff += struct.pack("<H", 2)
    tiff += struct.pack("<HHII", TAG_DATETIME_ORIGINAL, _ASCII, len(value), values_at)
    tiff += struct.pack("<HHII", TAG_DATETIME_DIGITIZED, _ASCII, len(value), values_at + len(value))
    tiff += struct.pack("<I", 0) + value + value
    return _app1(_EXIF_MARK + bytes(tiff))


def _insert_segment(data: bytes, stamp: str) -> tuple[bytes, dict[str, Any]]:
    segments = _jpeg_segments(data)
    at = segments[0][2] if segments and segments[0][0] == 0xE0 else 2
    segment = _minimal_exif_segment(stamp)
    return data[:at] + segment + data[at:], {"v": _ORIGINAL_VERSION, "mode": "inserted", "length": len(segment)}


def _replace_segment(data: bytes, start: int, end: int, stamp: str) -> tuple[bytes, dict[str, Any]]:
    from PIL import Image  # nur für diesen Fall; der Rest des Moduls kommt ohne aus

    original = data[start:end]
    exif = Image.Exif()
    try:
        exif.load(original[4:])
        exif_ifd = dict(exif.get_ifd(_EXIF_IFD_TAG)) if _EXIF_IFD_TAG in exif else {}
    except Exception as exc:  # noqa: BLE001 - defekter EXIF-Block: Datei bleibt unverändert
        raise ExifDateUnsupported("EXIF-Block nicht lesbar") from exc
    exif_ifd[TAG_DATETIME_ORIGINAL] = stamp
    exif_ifd[TAG_DATETIME_DIGITIZED] = stamp
    if _EXIF_IFD_TAG in exif:
        del exif[_EXIF_IFD_TAG]
    exif[_EXIF_IFD_TAG] = exif_ifd
    try:
        payload = exif.tobytes()
    except Exception as exc:  # noqa: BLE001 - nicht serialisierbare Werte: Datei bleibt unverändert
        raise ExifDateUnsupported("EXIF-Block nicht schreibbar") from exc
    replacement = _app1(payload)
    record = {"v": _ORIGINAL_VERSION, "mode": "replaced", "segment": base64.b64encode(original).decode("ascii")}
    return data[:start] + replacement + data[end:], record


# --- Öffentliche Funktionen ---------------------------------------------------------------


def stamp_is_valid(stamp: str) -> bool:
    return bool(_STAMP.match(stamp or ""))


def write_capture_date(data: bytes, stamp: str, *, record_original: bool) -> tuple[bytes, dict[str, Any] | None]:
    """(neue Bytes, Original-Datensatz oder None). ``stamp`` = "JJJJ:MM:TT HH:MM:SS".
    record_original=False, wenn hocX schon einmal geschrieben hat - dann gibt es nie ein zweites
    Original, und die Datei muss ihr Datum über ``inplace`` finden (sonst ExifDateError)."""
    if not stamp_is_valid(stamp):
        raise ExifDateError("Ungültiger Zeitstempel")
    buffer = bytearray(data)
    blocks, slots = _find_slots(buffer)
    if any(slot.tag == TAG_DATETIME_ORIGINAL for slot in slots):
        if _overlapping(slots):
            # Zwei Felder teilen sich Bytes - so schreibt keine Kamera; Rückweg wäre nicht eindeutig.
            raise ExifDateUnsupported("Datumsfelder überlappen")
        value = stamp.encode("ascii")
        originals = [
            {"b": slot.block, "t": slot.tag, "raw": bytes(buffer[slot.offset:slot.offset + slot.length]).hex()} for slot in slots
        ]
        for slot in slots:
            buffer[slot.offset:slot.offset + slot.length] = value + b"\x00" * (slot.length - len(value))
        _fix_png_crcs(buffer, blocks, {slot.block for slot in slots})
        # Ein Wert, der in die IFD-Struktur selbst zeigt, hätte sie zerstört: dann wäre auch der
        # Rückweg weg. Nach dem Schreiben müssen dieselben Felder an derselben Stelle stehen.
        if _find_slots(buffer)[1] != slots:
            raise ExifDateUnsupported("EXIF-Struktur nach dem Schreiben verändert")
        record = {"v": _ORIGINAL_VERSION, "mode": "inplace", "slots": originals} if record_original else None
        return bytes(buffer), record
    if not record_original:
        # hocX hat geschrieben, aber das Datum ist nicht mehr auffindbar: die Datei wurde
        # ausserhalb verändert - nicht raten.
        raise ExifDateError("Geschriebenes Aufnahmedatum nicht mehr auffindbar")
    if data[:2] != b"\xff\xd8":
        raise ExifDateUnsupported("Format ohne DateTimeOriginal")
    existing = _first_exif_segment(data)
    if existing is None:
        return _insert_segment(data, stamp)
    return _replace_segment(data, existing[0], existing[1], stamp)


def parse_original(record: Any) -> dict[str, Any]:
    """Prüft einen gespeicherten Original-Datensatz streng (er kann aus einem Mandanten-Import
    stammen) und gibt ihn zurück; ExifDateError, wenn er nicht passt."""
    if not isinstance(record, dict) or record.get("v") != _ORIGINAL_VERSION:
        raise ExifDateError("Unbekannter Original-Datensatz")
    mode = record.get("mode")
    if mode == "inplace":
        slots = record.get("slots")
        if not isinstance(slots, list) or not slots or len(slots) > 3 * _MAX_EXIF_BLOCKS:
            raise ExifDateError("Ungültiger Original-Datensatz")
        for slot in slots:
            if not isinstance(slot, dict) or not isinstance(slot.get("b"), int) or not 0 <= slot["b"] < _MAX_EXIF_BLOCKS:
                raise ExifDateError("Ungültiger Original-Datensatz")
            if slot.get("t") not in _DATE_TAGS or not isinstance(slot.get("raw"), str):
                raise ExifDateError("Ungültiger Original-Datensatz")
            try:
                raw = bytes.fromhex(slot["raw"])
            except ValueError as exc:
                raise ExifDateError("Ungültiger Original-Datensatz") from exc
            if not _STAMP_LENGTH <= len(raw) <= _MAX_SLOT_LENGTH:
                raise ExifDateError("Ungültiger Original-Datensatz")
        return record
    if mode == "inserted":
        if not isinstance(record.get("length"), int) or not 30 <= record["length"] <= 512:
            raise ExifDateError("Ungültiger Original-Datensatz")
        return record
    if mode == "replaced":
        try:
            segment = base64.b64decode(record.get("segment") or "", validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ExifDateError("Ungültiger Original-Datensatz") from exc
        if (
            len(segment) < 14 or segment[:2] != b"\xff\xe1" or segment[4:10] != _EXIF_MARK
            or struct.unpack(">H", segment[2:4])[0] + 2 != len(segment)
        ):
            raise ExifDateError("Ungültiger Original-Datensatz")
        return record
    raise ExifDateError("Unbekannter Original-Datensatz")


def restore_capture_date(data: bytes, record: Any) -> bytes:
    """Setzt die Datumsfelder auf den Stand vor dem ersten Schreiben zurück (siehe Moduldocstring).
    Alles oder nichts: passt die Datei nicht mehr zum Datensatz, ExifDateError ohne Änderung."""
    record = parse_original(record)
    mode = record["mode"]
    if mode == "inplace":
        buffer = bytearray(data)
        blocks, slots = _find_slots(buffer)
        by_key = {(slot.block, slot.tag): slot for slot in slots}
        writes = []
        for entry in record["slots"]:
            raw = bytes.fromhex(entry["raw"])
            slot = by_key.get((entry["b"], entry["t"]))
            if slot is None or slot.length != len(raw):
                raise ExifDateError("Datumsfeld nicht mehr auffindbar")
            writes.append((slot, raw))
        for slot, raw in writes:
            buffer[slot.offset:slot.offset + slot.length] = raw
        _fix_png_crcs(buffer, blocks, {slot.block for slot, _raw in writes})
        return bytes(buffer)
    try:
        existing = _first_exif_segment(data)
    except ExifDateUnsupported as exc:
        raise ExifDateError("JPEG nicht mehr lesbar") from exc
    if existing is None:
        raise ExifDateError("EXIF-Segment nicht mehr auffindbar")
    start, end = existing
    if mode == "inserted":
        if end - start != record["length"]:
            raise ExifDateError("Eingefügtes EXIF-Segment wurde verändert")
        return data[:start] + data[end:]
    return data[:start] + base64.b64decode(record["segment"]) + data[end:]


def read_date_values(data: bytes) -> list[tuple[int, int, bytes]]:
    """(Block, Tag, Rohwert) aller gefundenen Datumsfelder - für Tests und Diagnose."""
    buffer = bytearray(data)
    _blocks, slots = _find_slots(buffer)
    return [(slot.block, slot.tag, bytes(buffer[slot.offset:slot.offset + slot.length])) for slot in slots]


__all__ = [
    "ExifDateError", "ExifDateUnsupported", "TAG_DATETIME", "TAG_DATETIME_DIGITIZED", "TAG_DATETIME_ORIGINAL",
    "parse_original", "read_date_values", "restore_capture_date", "stamp_is_valid", "write_capture_date",
]
