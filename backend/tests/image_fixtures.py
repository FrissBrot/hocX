"""Gemeinsame Testbilder mit gezielt gesetzten EXIF-/GPS-Werten (siehe test_image_*.py)."""

from __future__ import annotations

import io
from datetime import datetime

from PIL import Image
from PIL.TiffImagePlugin import IFDRational


def dms(value: float) -> tuple[IFDRational, IFDRational, IFDRational]:
    value = abs(value)
    degrees = int(value)
    minutes = int((value - degrees) * 60)
    seconds = round(((value - degrees) * 60 - minutes) * 60 * 100)
    return IFDRational(degrees, 1), IFDRational(minutes, 1), IFDRational(seconds, 100)


def build_exif(
    *,
    taken_at: datetime | None = None,
    offset: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    altitude: float | None = None,
    direction: float | None = None,
    make: str | None = None,
    model: str | None = None,
    orientation: int | None = None,
) -> Image.Exif:
    exif = Image.Exif()
    if make:
        exif[0x010F] = make
    if model:
        exif[0x0110] = model
    if orientation:
        exif[0x0112] = orientation
    exif_ifd = {}
    if taken_at is not None:
        exif_ifd[0x9003] = taken_at.strftime("%Y:%m:%d %H:%M:%S")
    if offset is not None:
        exif_ifd[0x9011] = offset
    if exif_ifd:
        exif[0x8769] = exif_ifd
    if latitude is not None and longitude is not None:
        gps = {
            0: b"\x02\x03\x00\x00",
            1: "S" if latitude < 0 else "N",
            2: dms(latitude),
            3: "W" if longitude < 0 else "E",
            4: dms(longitude),
        }
        if altitude is not None:
            gps[5] = b"\x01" if altitude < 0 else b"\x00"
            gps[6] = IFDRational(round(abs(altitude) * 10), 10)
        if direction is not None:
            gps[16] = "T"
            gps[17] = IFDRational(round(direction * 100), 100)
        exif[0x8825] = gps
    return exif


def jpeg(color=(10, 20, 30), size=(32, 24), **exif_values) -> bytes:
    buffer = io.BytesIO()
    exif = build_exif(**exif_values)
    Image.new("RGB", size, color=color).save(buffer, format="JPEG", exif=exif.tobytes() if len(exif) else b"")
    return buffer.getvalue()


def png(color=(10, 20, 30), size=(32, 24), **exif_values) -> bytes:
    buffer = io.BytesIO()
    exif = build_exif(**exif_values)
    Image.new("RGB", size, color=color).save(buffer, format="PNG", exif=exif.tobytes() if len(exif) else b"")
    return buffer.getvalue()


def webp(color=(10, 20, 30), size=(32, 24), **exif_values) -> bytes:
    buffer = io.BytesIO()
    exif = build_exif(**exif_values)
    Image.new("RGB", size, color=color).save(buffer, format="WEBP", exif=exif.tobytes() if len(exif) else b"")
    return buffer.getvalue()


def gif(size=(8, 8)) -> bytes:
    buffer = io.BytesIO()
    Image.new("P", size).save(buffer, format="GIF")
    return buffer.getvalue()


def read_exif(content: bytes) -> tuple[dict, dict, dict]:
    with Image.open(io.BytesIO(content)) as image:
        exif = image.getexif()
        return dict(exif), dict(exif.get_ifd(0x8769)), dict(exif.get_ifd(0x8825))


def response_bytes(response) -> bytes:
    """Inhalt einer Download-Antwort: FileResponse (Pfad), Response (Bytes, z. B. bereinigte
    Exportfassung) oder StreamingResponse (Objekt aus S3)."""
    from pathlib import Path

    path = getattr(response, "path", None)
    if path:
        return Path(path).read_bytes()
    if getattr(response, "body_iterator", None) is None:
        return bytes(response.body)
    import asyncio

    async def collect() -> bytes:
        return b"".join([chunk if isinstance(chunk, bytes) else chunk.encode() async for chunk in response.body_iterator])

    return asyncio.run(collect())
