"""Pfade und Dateiarten für den Datei-Import - rein, ohne I/O.

Ein Pfad aus einem ZIP oder aus dem Browser (webkitRelativePath) wird nie als Dateisystempfad
verwendet (Zip-Slip ausgeschlossen: die Pipeline vergibt eigene Objekt-Keys). Er dient nur den
Regeln, der Anzeige und als Dateiname. Trotzdem wird er streng normalisiert: «\\» → «/»,
Steuer- und Bidi-Zeichen entfernt, Unicode NFC, «.»/«..»/leere Segmente verworfen.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import PurePosixPath

from app.services.upload_pipeline import DOCUMENT_UPLOAD_EXTENSIONS, GALLERY_DIRECT_IMAGE_MAX_BYTES, MAX_UPLOAD_BYTES

MAX_PATH_LENGTH = 1024
MAX_NAME_LENGTH = 255
MAX_DEPTH = 64

IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".heic", ".heif"})
DOCUMENT_EXTENSIONS = frozenset(DOCUMENT_UPLOAD_EXTENSIONS)

KIND_IMAGE = "image"
KIND_DOCUMENT = "document"
KIND_OTHER = "other"

# Grenzen je Datei = die bestehenden Upload-Grenzen (User-Entscheid E-5).
MAX_BYTES_BY_KIND = {KIND_IMAGE: GALLERY_DIRECT_IMAGE_MAX_BYTES, KIND_DOCUMENT: MAX_UPLOAD_BYTES}

_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
# Bidi-Steuerzeichen (Trojan-Source-artige Anzeige-Tricks) und unsichtbare Formatzeichen
_BIDI = re.compile("[؜​-‏‪-‮⁦-⁩﻿]")
# Systemdateien, die beim Ordner-Upload und in ZIPs vorkommen, aber nie gemeint sind
_HIDDEN_NAMES = frozenset({"thumbs.db", "desktop.ini", "icon\r"})
_HIDDEN_SEGMENTS = frozenset({"__macosx"})


def normalize_path(raw: str | None) -> str | None:
    """Normalisierter relativer Pfad oder None, wenn nichts Brauchbares übrig bleibt."""
    if not raw:
        return None
    text = unicodedata.normalize("NFC", raw.replace("\\", "/"))
    text = _BIDI.sub("", _CONTROL.sub("", text))
    segments = [segment.strip() for segment in text.split("/")]
    segments = [segment for segment in segments if segment and segment not in (".", "..")]
    if not segments or len(segments) > MAX_DEPTH:
        return None
    if any(len(segment) > MAX_NAME_LENGTH for segment in segments):
        return None
    path = "/".join(segments)
    return path if len(path) <= MAX_PATH_LENGTH else None


def file_name(path: str) -> str:
    return PurePosixPath(path).name


def folder_of(path: str) -> str:
    """Ordnerpfad ohne Dateinamen ('' auf oberster Ebene)."""
    parent = PurePosixPath(path).parent.as_posix()
    return "" if parent == "." else parent


def folder_segments(path: str) -> list[str]:
    folder = folder_of(path)
    return folder.split("/") if folder else []


def is_hidden(path: str) -> bool:
    """Versteckte/System-Dateien (.DS_Store, __MACOSX, Thumbs.db) - werden gar nicht aufgeführt."""
    segments = path.split("/")
    if any(segment.lower() in _HIDDEN_SEGMENTS for segment in segments):
        return True
    name = segments[-1]
    return name.startswith(".") or name.lower() in _HIDDEN_NAMES


def kind_for_name(name: str) -> str:
    suffix = PurePosixPath(name).suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return KIND_IMAGE
    if suffix in DOCUMENT_EXTENSIONS:
        return KIND_DOCUMENT
    return KIND_OTHER


def listing_code(kind: str, size: int) -> str | None:
    """Grund, warum eine Datei schon nach dem Auflisten nicht importiert werden kann (Bericht)."""
    if kind == KIND_OTHER:
        return "unsupported_format"
    if size > MAX_BYTES_BY_KIND[kind]:
        return "too_large"
    return None


# --- Google Takeout -------------------------------------------------------------------------
# Ein Takeout-Archiv beginnt mit «Takeout/<Produkt>/…». Der Präfix «Takeout/» wird für Regeln
# und Anzeige entfernt (der Benutzer sieht seine eigene Ordnerordnung). Begleitdateien
# (Metadaten-JSON je Foto, archive_browser.html) werden nicht importiert, sondern als
# «Takeout-Metadaten» übersprungen. Das Aufnahmedatum aus den JSON-Dateien wertet P0 bewusst
# nicht aus (im Plan nicht vorgesehen) - massgeblich bleibt EXIF bzw. die Datumsregel.
TAKEOUT_ROOT = "Takeout"
_TAKEOUT_SIDECAR_NAMES = frozenset({"archive_browser.html"})


def is_takeout(paths: list[str]) -> bool:
    return bool(paths) and all(path.split("/", 1)[0] == TAKEOUT_ROOT and "/" in path for path in paths)


def strip_takeout(path: str) -> str:
    head, _sep, rest = path.partition("/")
    return rest if head == TAKEOUT_ROOT and rest else path


def is_takeout_sidecar(path: str) -> bool:
    name = file_name(path).lower()
    return name.endswith(".json") or name in _TAKEOUT_SIDECAR_NAMES
