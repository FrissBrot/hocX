"""Entfernt Foto-Metadaten, die beim oeffentlichen Teilen (share_link) nicht mitgehen sollen.

Drei Kategorien, je ein Schalter am Link (siehe ShareLink.share_location/_capture_date/_camera):

- Standort: das komplette GPS-IFD.
- Aufnahmedatum: DateTime/DateTimeOriginal/DateTimeDigitized samt Zeitzonen-/Subsekunden-Tags.
- Kamera & Geraet: alles, was nicht rein technisch zur Darstellung noetig ist (Hersteller, Modell,
  Software, Seriennummern, Objektiv, Belichtungswerte, MakerNote, Besitzername ...) - bewusst als
  Whitelist der technischen Tags statt als Blacklist, weil Hersteller beliebige weitere Tags
  schreiben.

Sobald auch nur eine Kategorie aus ist, fallen zusaetzlich XMP- und IPTC-Bloecke komplett weg:
sie koennen jede der drei Kategorien enthalten (Ort, Datum, Kamera) und lassen sich nicht
zuverlaessig feldweise filtern. Orientation bleibt immer erhalten, sonst stuenden Fotos quer.

JPEG/PNG/WebP werden verlustfrei auf Segment-/Chunk-Ebene umgeschrieben (kein Re-Encode). Bei
JPEG fallen dabei auch angehaengte Zusatzbilder (MPF: Tiefenkarten, HDR-Gain-Maps) weg, weil die
eigene Metadaten tragen koennen. TIFF wird ueber PIL neu geschrieben (verlustfrei, aber nur die
erste Seite). GIF/BMP tragen praktisch keine Metadaten und gehen unveraendert raus. Schlaegt das
Umschreiben fehl, wird das Bild ohne jegliche Metadaten neu kodiert - im Zweifel lieber
Qualitaet als Privatsphaere opfern."""

from __future__ import annotations

import io
import struct
import zlib
from dataclasses import dataclass

from PIL import Image, ImageOps


@dataclass(frozen=True)
class MetadataPolicy:
    location: bool
    capture_date: bool
    camera: bool

    @property
    def keeps_everything(self) -> bool:
        return self.location and self.capture_date and self.camera


SANITIZABLE_MIME_TYPES = frozenset({"image/jpeg", "image/png", "image/webp", "image/tiff"})

_EXIF_IFD = 0x8769
_GPS_IFD = 0x8825
_INTEROP_IFD = 0xA005
_ORIENTATION = 0x0112

# IFD0: zur korrekten Darstellung noetig (Ausrichtung, Aufloesung, Farbaufbau, TIFF-Struktur).
_IFD0_TECHNICAL = frozenset(
    {
        0x0100, 0x0101, 0x0102, 0x0103, 0x0106, 0x0111, 0x0112, 0x0115, 0x0116, 0x0117,
        0x011A, 0x011B, 0x011C, 0x0128, 0x013D, 0x013E, 0x013F, 0x0152,
        0x0211, 0x0212, 0x0213, 0x0214, 0x8773,
    }
)  # fmt: skip
_IFD0_DATE = frozenset({0x0132})
# Exif-IFD: Version, Farbraum, Pixelmasse.
_EXIF_TECHNICAL = frozenset({0x9000, 0x9101, 0xA000, 0xA001, 0xA002, 0xA003})
_EXIF_DATE = frozenset({0x9003, 0x9004, 0x9010, 0x9011, 0x9012, 0x9290, 0x9291, 0x9292})


def filter_exif(exif_bytes: bytes, policy: MetadataPolicy) -> bytes | None:
    """EXIF-Block (mit oder ohne "Exif\\0\\0"-Praefix) nach `policy` gefiltert, immer MIT
    Praefix zurueck; None, wenn nichts Behaltenswertes uebrig bleibt."""
    exif = Image.Exif()
    exif.load(exif_bytes)
    exif_ifd = dict(exif.get_ifd(_EXIF_IFD)) if _EXIF_IFD in exif else {}

    for tag in list(exif.keys()):
        if tag in (_EXIF_IFD, _GPS_IFD):
            continue
        if tag in _IFD0_DATE:
            if not policy.capture_date:
                del exif[tag]
        elif not policy.camera and tag not in _IFD0_TECHNICAL:
            del exif[tag]

    if _GPS_IFD in exif and not policy.location:
        del exif[_GPS_IFD]

    for tag in list(exif_ifd):
        if tag in _EXIF_DATE:
            if not policy.capture_date:
                del exif_ifd[tag]
        elif not policy.camera and tag not in _EXIF_TECHNICAL:
            del exif_ifd[tag]
    exif_ifd.pop(_INTEROP_IFD, None)
    if _EXIF_IFD in exif:
        del exif[_EXIF_IFD]
    if exif_ifd:
        exif[_EXIF_IFD] = exif_ifd

    if not len(exif):
        return None
    return exif.tobytes()


def _filter_exif_or_orientation(exif_bytes: bytes, policy: MetadataPolicy) -> bytes | None:
    """Wie filter_exif, faellt bei unlesbarem EXIF aber auf "nur Orientation" bzw. nichts zurueck."""
    try:
        return filter_exif(exif_bytes, policy)
    except Exception:
        try:
            original = Image.Exif()
            original.load(exif_bytes)
            orientation = original.get(_ORIENTATION)
        except Exception:
            return None
        if orientation is None:
            return None
        minimal = Image.Exif()
        minimal[_ORIENTATION] = orientation
        return minimal.tobytes()


# --- JPEG ---------------------------------------------------------------------------------

_APP1 = 0xE1
_APP2 = 0xE2
_SOS = 0xDA
_EOI = 0xD9


def _sanitize_jpeg(data: bytes, policy: MetadataPolicy) -> bytes:
    if data[:2] != b"\xff\xd8":
        raise ValueError("kein JPEG")
    out = bytearray(data[:2])
    pos = 2
    size = len(data)
    in_scan = False
    while pos < size:
        if in_scan:
            # Entropie-kodierte Daten: bis zum naechsten echten Marker (nicht FF00-Stuffing,
            # nicht RSTn) durchkopieren.
            start = pos
            while True:
                pos = data.index(b"\xff", pos)
                following = data[pos + 1]
                if following == 0x00 or 0xD0 <= following <= 0xD7 or following == 0xFF:
                    pos += 1 if following == 0xFF else 2
                    continue
                break
            out += data[start:pos]
            in_scan = False
            continue
        if data[pos] != 0xFF:
            raise ValueError("defektes JPEG-Segment")
        marker = data[pos + 1]
        if marker == 0xFF:
            pos += 1
            continue
        if marker == _EOI:
            # Alles danach (MPF-Zusatzbilder, Trailer) faellt bewusst weg.
            out += b"\xff\xd9"
            return bytes(out)
        if 0xD0 <= marker <= 0xD7 or marker == 0x01:
            out += data[pos : pos + 2]
            pos += 2
            continue
        (length,) = struct.unpack(">H", data[pos + 2 : pos + 4])
        segment = data[pos : pos + 2 + length]
        payload = segment[4:]
        pos += 2 + length
        if marker == _SOS:
            out += segment
            in_scan = True
            continue
        if marker == _APP1 and payload.startswith(b"Exif\x00\x00"):
            filtered = _filter_exif_or_orientation(payload, policy)
            if filtered is not None and len(filtered) + 2 <= 0xFFFF:
                out += b"\xff\xe1" + struct.pack(">H", len(filtered) + 2) + filtered
            continue
        if marker == _APP2 and not payload.startswith(b"ICC_PROFILE\x00"):
            continue  # MPF & Co. - die referenzierten Zusatzbilder fallen ohnehin weg
        if 0xE1 <= marker <= 0xED or marker == 0xEF:
            continue  # XMP, IPTC/Photoshop, Herstellerbloecke; APP0 (JFIF) und APP14 (Adobe) bleiben
        if marker == 0xFE:
            continue  # Kommentar
        out += segment
    raise ValueError("JPEG ohne EOI")


# --- PNG ----------------------------------------------------------------------------------

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)


def _sanitize_png(data: bytes, policy: MetadataPolicy) -> bytes:
    if not data.startswith(_PNG_SIGNATURE):
        raise ValueError("kein PNG")
    out = bytearray(_PNG_SIGNATURE)
    pos = len(_PNG_SIGNATURE)
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        kind = data[pos + 4 : pos + 8]
        chunk = data[pos : pos + 12 + length]
        payload = data[pos + 8 : pos + 8 + length]
        pos += 12 + length
        if kind == b"eXIf":
            filtered = _filter_exif_or_orientation(payload, policy)
            if filtered is not None:
                out += _png_chunk(b"eXIf", filtered.removeprefix(b"Exif\x00\x00"))
            continue
        if kind in (b"tEXt", b"zTXt", b"iTXt"):
            continue  # XMP, "Raw profile type exif", Kommentare, Erstellungszeit
        if kind == b"tIME" and not policy.capture_date:
            continue
        out += chunk
        if kind == b"IEND":
            return bytes(out)
    raise ValueError("PNG ohne IEND")


# --- WebP ---------------------------------------------------------------------------------

_VP8X_EXIF_FLAG = 0x08
_VP8X_XMP_FLAG = 0x04


def _sanitize_webp(data: bytes, policy: MetadataPolicy) -> bytes:
    if data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        raise ValueError("kein WebP")
    chunks: list[tuple[bytes, bytes]] = []
    pos = 12
    while pos + 8 <= len(data):
        kind = data[pos : pos + 4]
        (length,) = struct.unpack("<I", data[pos + 4 : pos + 8])
        payload = data[pos + 8 : pos + 8 + length]
        pos += 8 + length + (length & 1)
        if kind == b"EXIF":
            filtered = _filter_exif_or_orientation(payload, policy)
            if filtered is not None:
                chunks.append((kind, filtered.removeprefix(b"Exif\x00\x00")))
            continue
        if kind == b"XMP ":
            continue
        chunks.append((kind, payload))
    has_exif = any(kind == b"EXIF" for kind, _ in chunks)
    body = bytearray(b"WEBP")
    for kind, payload in chunks:
        if kind == b"VP8X":
            flags = payload[0] & ~_VP8X_XMP_FLAG
            flags = flags | _VP8X_EXIF_FLAG if has_exif else flags & ~_VP8X_EXIF_FLAG
            payload = bytes([flags]) + payload[1:]
        body += kind + struct.pack("<I", len(payload)) + payload
        if len(payload) & 1:
            body += b"\x00"
    return b"RIFF" + struct.pack("<I", len(body)) + bytes(body)


# --- TIFF / Fallback ----------------------------------------------------------------------


def _reencode_without_metadata(data: bytes, mime_type: str, policy: MetadataPolicy) -> bytes:
    """Neu schreiben ueber PIL. Image.copy() verliert tag_v2/info, damit nimmt PIL keine
    XMP-/IPTC-Bloecke des Originals mit; EXIF kommt nur gefiltert zurueck."""
    with Image.open(io.BytesIO(data)) as image:
        exif_bytes = image.info.get("exif")
        if exif_bytes is None and hasattr(image, "getexif"):
            raw = image.getexif()
            exif_bytes = raw.tobytes() if len(raw) else None
        filtered = _filter_exif_or_orientation(exif_bytes, policy) if exif_bytes else None
        image.load()
        clean = image.copy()
    buffer = io.BytesIO()
    if mime_type == "image/tiff":
        clean.save(buffer, format="TIFF", exif=filtered or b"")  # ohne libtiff-Kompression: die verwirft sonst Tags wie DateTime
    elif mime_type == "image/png":
        clean.save(buffer, format="PNG", exif=filtered or b"")
    elif mime_type == "image/webp":
        clean.save(buffer, format="WEBP", lossless=False, quality=95, exif=filtered or b"")
    else:
        if clean.mode not in ("RGB", "L"):
            clean = clean.convert("RGB")
        clean.save(buffer, format="JPEG", quality=95, exif=filtered or b"")
    return buffer.getvalue()


def sanitize_image(data: bytes, mime_type: str | None, policy: MetadataPolicy) -> bytes:
    """`data` ohne die per `policy` ausgeschlossenen Metadaten. Unveraendert, wenn alles geteilt
    werden darf oder der Typ keine relevanten Metadaten traegt."""
    if policy.keeps_everything or mime_type not in SANITIZABLE_MIME_TYPES:
        return data
    try:
        if mime_type == "image/jpeg":
            return _sanitize_jpeg(data, policy)
        if mime_type == "image/png":
            return _sanitize_png(data, policy)
        if mime_type == "image/webp":
            return _sanitize_webp(data, policy)
    except Exception:
        pass  # Bewusst kein Fehler-Log: der verlustbehaftete Fallback unten liefert trotzdem ein sauberes Bild
    try:
        return _reencode_without_metadata(data, mime_type, policy)
    except Exception:
        pass  # letzte Stufe unten; schlaegt auch die fehl, propagiert der Fehler zum globalen Handler
    # Pixel ohne jegliche Metadaten, Ausrichtung vorher angewendet.
    with Image.open(io.BytesIO(data)) as image:
        upright = ImageOps.exif_transpose(image)
        target = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP", "image/tiff": "TIFF"}[mime_type]
        if target == "JPEG" and upright.mode not in ("RGB", "L"):
            upright = upright.convert("RGB")
        buffer = io.BytesIO()
        upright.save(buffer, format=target, **({"quality": 95} if target in ("JPEG", "WEBP") else {}))
        return buffer.getvalue()
