"""Apple-Fotoformate fuer die Galerie: HEIC/HEIF-Bilder und Live Photos.

Browser koennen HEIC ausserhalb von Safari nicht anzeigen, und alles hinter dem Upload
(Thumbnails, Aehnlichkeits-/Qualitaetsanalyse, der photo-analysis-worker mit OpenCV, PDF-Export)
erwartet Formate, die Pillow/OpenCV ohne Zusatzcodec lesen. Deshalb wird ein HEIC beim Upload
einmal nach JPEG umgewandelt (convert_heic_to_jpeg) und nur das JPEG gespeichert - alles
Nachgelagerte bleibt unveraendert. Preis: Das HEIC-Original selbst (10-Bit, HDR-Gain-Map) wird
nicht aufbewahrt; EXIF (Aufnahmedatum, Kamera) und das ICC-Profil (Display-P3) bleiben erhalten.

Ein Live Photo besteht beim Export aus zwei Dateien mit gleichem Namen: IMG_1234.HEIC (das
Standbild) und IMG_1234.MOV (ca. 3 s Video, oft HEVC). pair_live_clips ordnet sie ueber den
Dateinamen zu; transcode_live_clip macht aus dem MOV ein kleines, ueberall abspielbares
H.264-MP4, das die Galerie beim Hovern ueber dem Bild abspielt."""

from __future__ import annotations

import io
import shutil
import subprocess
import tempfile
from pathlib import Path, PurePosixPath

import pillow_heif
from PIL import Image, ImageOps

from app.core.config import settings

pillow_heif.register_heif_opener()

# ftyp-Hauptmarken (Bytes 8-12) von HEIC/HEIF-Dateien; "mif1"/"msf1" sind die generischen
# HEIF-Marken, die iPhones und einige Android-Kameras verwenden.
_HEIF_BRANDS = {b"heic", b"heix", b"heim", b"heis", b"hevc", b"hevx", b"mif1", b"msf1"}
# Marken, mit denen iPhones ihre Live-Photo-Clips schreiben (QuickTime) bzw. wie ein
# nachtraeglich konvertiertes MP4 aussieht.
_CLIP_BRANDS = {b"qt  ", b"isom", b"iso2", b"mp41", b"mp42", b"M4V ", b"avc1"}

CLIP_EXTENSIONS = frozenset({".mov", ".mp4", ".m4v"})
HEIC_EXTENSIONS = frozenset({".heic", ".heif"})

MAX_LIVE_CLIP_BYTES = 30 * 1024 * 1024  # Eingabe, unkomprimierte iPhone-Clips sind ~3-6 MB
LIVE_CLIP_MAX_SECONDS = 6
LIVE_CLIP_MAX_WIDTH = 1280
LIVE_CLIP_TRANSCODE_TIMEOUT_SECONDS = 90
HEIC_MAX_PIXELS = 120_000_000  # Schutz gegen Dekompressionsbomben, ein 48-MP-iPhone-Foto hat 48 M
HEIC_JPEG_QUALITY = 92


def _ftyp_brand(content: bytes) -> bytes | None:
    if len(content) >= 12 and content[4:8] == b"ftyp":
        return content[8:12]
    return None


def is_heic(content: bytes) -> bool:
    return _ftyp_brand(content) in _HEIF_BRANDS


def is_live_clip(content: bytes) -> bool:
    return _ftyp_brand(content) in _CLIP_BRANDS


def convert_heic_to_jpeg(content: bytes) -> bytes | None:
    """HEIC/HEIF -> JPEG (Bildausrichtung eingerechnet, EXIF und ICC-Profil uebernommen).
    None, wenn die Datei nicht dekodierbar ist (abgeschnitten, unbekannter Codec) oder
    unverhaeltnismaessig gross waere."""
    try:
        with Image.open(io.BytesIO(content)) as image:
            if image.width * image.height > HEIC_MAX_PIXELS:
                return None
            image = ImageOps.exif_transpose(image)
            exif = image.getexif()
            icc_profile = image.info.get("icc_profile")
            if image.mode not in ("RGB", "L"):
                image = image.convert("RGB")
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=HEIC_JPEG_QUALITY, exif=exif, icc_profile=icc_profile)
            return buffer.getvalue()
    except Exception:
        return None


def jpeg_filename(filename: str) -> str:
    """IMG_1234.HEIC -> IMG_1234.jpg - der gespeicherte Name soll zum gespeicherten Format passen."""
    return str(PurePosixPath(filename or "bild").with_suffix(".jpg"))


def _pair_key(name: str) -> str:
    path = PurePosixPath(name.replace("\\", "/"))
    return str(path.with_suffix("")).lower()


def pair_live_clips(names: list[str]) -> dict[int, int]:
    """Live-Photo-Zuordnung anhand der Dateinamen: {Index des Bildes: Index des Clips}. Ein
    Clip (.mov/.mp4/.m4v) gehoert zum Bild mit gleichem Namen ohne Endung (gleicher Ordner,
    Gross-/Kleinschreibung egal). Jeder Clip wird hoechstens einem Bild zugeordnet; ein Clip
    ohne Bild bleibt ausserhalb des Ergebnisses."""
    clip_by_key: dict[str, int] = {}
    for index, name in enumerate(names):
        if PurePosixPath(name.replace("\\", "/")).suffix.lower() in CLIP_EXTENSIONS:
            clip_by_key.setdefault(_pair_key(name), index)
    pairs: dict[int, int] = {}
    for index, name in enumerate(names):
        if PurePosixPath(name.replace("\\", "/")).suffix.lower() in CLIP_EXTENSIONS:
            continue
        clip_index = clip_by_key.pop(_pair_key(name), None)
        if clip_index is not None:
            pairs[index] = clip_index
    return pairs


def transcode_live_clip(content: bytes) -> bytes | None:
    """Live-Photo-Clip -> H.264-MP4 (max. 6 s, max. 1280 px breit, ohne Ton, faststart), das
    jeder Browser inline abspielt - iPhone-Clips sind haeufig HEVC, das Chrome/Firefox nicht
    ueberall koennen. None, wenn ffmpeg fehlt oder die Datei kein lesbares Video ist; die
    Galerie zeigt das Bild dann als normales Foto. ffmpeg bekommt nur Dateizugriff
    (-protocol_whitelist file), damit ein praeparierter Container nichts nachladen kann."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None or len(content) > MAX_LIVE_CLIP_BYTES:
        return None
    # Auf einer echten Platte (nicht /tmp, das im Release-Deployment ein RAM-Tmpfs ist).
    work_root = Path(settings.upload_root) / "_staging" / "live"
    work_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=work_root) as work_dir:
        source = Path(work_dir) / "in.mov"
        target = Path(work_dir) / "out.mp4"
        source.write_bytes(content)
        command = [
            ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error",
            "-protocol_whitelist", "file",
            "-i", str(source),
            "-t", str(LIVE_CLIP_MAX_SECONDS),
            "-an",
            "-vf", f"scale='min({LIVE_CLIP_MAX_WIDTH},iw)':-2,format=yuv420p",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
            "-movflags", "+faststart",
            "-y", str(target),
        ]
        try:
            subprocess.run(command, check=True, capture_output=True, timeout=LIVE_CLIP_TRANSCODE_TIMEOUT_SECONDS)
        except (subprocess.SubprocessError, OSError):
            return None
        try:
            output = target.read_bytes()
        except OSError:
            return None
    return output or None
