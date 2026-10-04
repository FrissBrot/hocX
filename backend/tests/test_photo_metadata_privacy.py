"""photo_metadata_privacy.sanitize_image: welche Metadaten je Schalter erhalten bleiben, und dass
die Bilddaten bei JPEG verlustfrei (ohne Re-Encode) bleiben."""

import io
import struct

import pytest
from PIL import Image

from app.services.photo_metadata_privacy import MetadataPolicy, sanitize_image

GPS, EXIF_IFD = 0x8825, 0x8769
ORIENTATION, MAKE, MODEL, DATETIME = 0x0112, 0x010F, 0x0110, 0x0132
DATETIME_ORIGINAL, BODY_SERIAL, COLOR_SPACE = 0x9003, 0xA431, 0xA001

NOTHING = MetadataPolicy(location=False, capture_date=False, camera=False)
EVERYTHING = MetadataPolicy(location=True, capture_date=True, camera=True)


def _exif() -> Image.Exif:
    exif = Image.Exif()
    exif[ORIENTATION] = 6
    exif[MAKE] = "Canon"
    exif[MODEL] = "EOS R6"
    exif[DATETIME] = "2026:07:14 10:00:00"
    exif[GPS] = {1: "N", 2: (47.0, 3.0, 0.0), 3: "E", 4: (8.0, 15.0, 0.0)}
    exif[EXIF_IFD] = {DATETIME_ORIGINAL: "2026:07:14 10:00:00", BODY_SERIAL: "SERIAL123", COLOR_SPACE: 1}
    return exif


def _jpeg(*, xmp: bool = False, trailer: bytes = b"") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (16, 12), "white").save(buffer, format="JPEG", exif=_exif().tobytes())
    data = buffer.getvalue()
    if xmp:
        payload = b"http://ns.adobe.com/xap/1.0/\x00<x:xmpmeta><exif:GPSLatitude>47,3N</exif:GPSLatitude></x:xmpmeta>"
        data = data[:2] + b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload + data[2:]
    return data + trailer


def _read(content: bytes) -> tuple[Image.Exif, dict]:
    exif = Image.open(io.BytesIO(content)).getexif()
    return exif, dict(exif.get_ifd(EXIF_IFD))


def test_keeps_the_original_untouched_when_everything_is_shared():
    original = _jpeg(xmp=True)
    assert sanitize_image(original, "image/jpeg", EVERYTHING) is original


@pytest.mark.parametrize(
    ("policy", "has_gps", "has_date", "has_camera"),
    [
        (MetadataPolicy(location=False, capture_date=True, camera=True), False, True, True),
        (MetadataPolicy(location=True, capture_date=False, camera=True), True, False, True),
        (MetadataPolicy(location=True, capture_date=True, camera=False), True, True, False),
        (NOTHING, False, False, False),
    ],
)
def test_jpeg_drops_exactly_the_disabled_categories(policy, has_gps, has_date, has_camera):
    exif, exif_ifd = _read(sanitize_image(_jpeg(), "image/jpeg", policy))

    assert (GPS in exif) is has_gps
    assert (DATETIME in exif) is has_date
    assert (DATETIME_ORIGINAL in exif_ifd) is has_date
    assert (MAKE in exif) is has_camera
    assert (MODEL in exif) is has_camera
    assert (BODY_SERIAL in exif_ifd) is has_camera
    assert exif[ORIENTATION] == 6  # nie entfernen, sonst stehen Fotos quer


def test_jpeg_keeps_technical_exif_and_the_image_data_bit_identical():
    original = _jpeg()
    cleaned = sanitize_image(original, "image/jpeg", NOTHING)

    _, exif_ifd = _read(cleaned)
    assert exif_ifd.get(COLOR_SPACE) == 1
    # Ab dem ersten Scan (SOS) identisch - kein Re-Encode, kein Qualitaetsverlust.
    assert cleaned[cleaned.index(b"\xff\xda") :] == original[original.index(b"\xff\xda") :]


def test_jpeg_drops_xmp_and_data_after_the_image():
    cleaned = sanitize_image(_jpeg(xmp=True, trailer=b"\xff\xd8MPF-Zusatzbild-mit-GPS\xff\xd9"), "image/jpeg", NOTHING)

    assert b"GPSLatitude" not in cleaned
    assert b"MPF-Zusatzbild" not in cleaned
    assert cleaned.endswith(b"\xff\xd9")
    Image.open(io.BytesIO(cleaned)).load()


@pytest.mark.parametrize(("mime_type", "fmt"), [("image/png", "PNG"), ("image/webp", "WEBP"), ("image/tiff", "TIFF")])
def test_other_formats_drop_location_and_keep_orientation(mime_type, fmt):
    buffer = io.BytesIO()
    Image.new("RGB", (16, 12), "white").save(buffer, format=fmt, exif=_exif().tobytes())

    cleaned = sanitize_image(buffer.getvalue(), mime_type, MetadataPolicy(location=False, capture_date=True, camera=False))

    exif, _ = _read(cleaned)
    assert GPS not in exif
    assert MAKE not in exif
    assert exif[DATETIME] == "2026:07:14 10:00:00"
    assert exif[ORIENTATION] == 6
    assert Image.open(io.BytesIO(cleaned)).format == fmt


def test_png_drops_text_chunks():
    buffer = io.BytesIO()
    from PIL.PngImagePlugin import PngInfo

    info = PngInfo()
    info.add_text("XML:com.adobe.xmp", "<x:xmpmeta>GPSLatitude</x:xmpmeta>")
    Image.new("RGB", (4, 3), "white").save(buffer, format="PNG", pnginfo=info)

    cleaned = sanitize_image(buffer.getvalue(), "image/png", NOTHING)

    assert b"GPSLatitude" not in cleaned
    Image.open(io.BytesIO(cleaned)).load()


def test_non_images_pass_through_unchanged():
    assert sanitize_image(b"%PDF-1.7", "application/pdf", NOTHING) == b"%PDF-1.7"


def test_generated_thumbnails_carry_no_metadata():
    """Die oeffentliche Vorschau (/thumbnail) laeuft nicht durch sanitize_image - sie darf deshalb
    selbst gar keine Metadaten enthalten."""
    from app.services.upload_pipeline import generate_thumbnail_bytes

    thumbnail, _, _ = generate_thumbnail_bytes(_jpeg(xmp=True))

    assert len(Image.open(io.BytesIO(thumbnail)).getexif()) == 0
    assert b"GPSLatitude" not in thumbnail
