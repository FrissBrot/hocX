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


# --- Takeout-Metadaten (User-Entscheid 2026-11-22) -------------------------------------------
# Google Fotos legt je Foto eine JSON-Datei daneben: «IMG_1.jpg.json», seit 2024
# «IMG_1.jpg.supplemental-metadata.json», bei langen Namen gekürzt («….jpg.supplemen.json», ganzer
# Name höchstens ~51 Zeichen) und bei gleichen Namen mit Zähler «IMG_1.jpg(1).json» für «IMG_1(1).jpg».
# Ausgewertet wird nur photoTakenTime.timestamp; das Datum gilt nur, wenn die Datei selbst keins hat.
TAKEOUT_JSON_MAX_BYTES = 64 * 1024
_SUPPLEMENTAL = "supplemental-metadata"
_COUNTER = re.compile(r"^(.*)\((\d{1,4})\)$")
# Google kürzt den JSON-Dateinamen auf rund 51 Zeichen - kürzere Namen gelten nie als gekürzt.
_TRUNCATED_MIN_LENGTH = 40
# Index der gekürzten Namen: so viele Anfangszeichen; mehr Kandidaten je Schlüssel = keine Zuordnung
_TRUNCATED_KEY = 20
_TRUNCATED_BUCKET_MAX = 50
# Je Archiv höchstens so viele Metadaten-JSON bzw. Bytes lesen (danach ohne Takeout-Datum)
TAKEOUT_JSON_MAX_FILES = 50_000
TAKEOUT_JSON_MAX_TOTAL_BYTES = 256 * 1024**2


def _sidecar_base(json_name: str) -> tuple[str, int | None] | None:
    """(Name des zugehörigen Bildes ohne Zähler, Zähler) aus dem Namen einer Takeout-JSON."""
    if not json_name.lower().endswith(".json"):
        return None
    stem = json_name[:-5]
    counter: int | None = None
    match = _COUNTER.match(stem)
    if match:
        stem, counter = match.group(1), int(match.group(2))
    head, dot, tail = stem.rpartition(".")
    # «.supplemental-metadata» und jede gekürzte Form davon («.supplemen», «.su») entfernen
    if dot and tail and _SUPPLEMENTAL.startswith(tail.lower()) and head:
        stem = head
    return (stem, counter) if stem else None


def _with_counter(name: str, counter: int | None) -> str:
    if counter is None:
        return name
    path = PurePosixPath(name)
    return f"{path.stem}({counter}){path.suffix}"


def match_takeout_sidecars(all_paths: list[str]) -> dict[str, str]:
    """Bildpfad → Pfad der zugehörigen Metadaten-JSON im selben Ordner (nur eindeutige Treffer)."""
    by_folder: dict[str, list[tuple[str, str, int | None]]] = {}
    images_by_folder: dict[str, list[str]] = {}
    for path in all_paths:
        name = file_name(path)
        folder = folder_of(path)
        if name.lower().endswith(".json"):
            base = _sidecar_base(name)
            if base is not None:
                by_folder.setdefault(folder, []).append((path, base[0], base[1]))
        elif kind_for_name(name) == KIND_IMAGE:
            images_by_folder.setdefault(folder, []).append(path)
    matches: dict[str, str] = {}
    for folder, images in images_by_folder.items():
        sidecars = by_folder.get(folder, [])
        if not sidecars:
            continue
        exact = {_with_counter(base, counter): json_path for json_path, base, counter in sidecars}
        # Gekürzte Namen einmal je Ordner nach den ersten Zeichen indexieren (kein quadratischer
        # Aufwand bei vielen Dateien ohne exakten Treffer, Security-Review M2)
        truncated: dict[str, list[tuple[str, str]]] = {}
        for json_path, base, counter in sidecars:
            if counter is None and len(file_name(json_path)) >= _TRUNCATED_MIN_LENGTH and len(base) >= _TRUNCATED_KEY:
                truncated.setdefault(base[:_TRUNCATED_KEY], []).append((json_path, base))
        for image in images:
            name = file_name(image)
            if name in exact:
                matches[image] = exact[name]
                continue
            bucket = truncated.get(name[:_TRUNCATED_KEY], [])
            candidates = [json_path for json_path, base in bucket[:_TRUNCATED_BUCKET_MAX] if name.startswith(base)]
            if len(candidates) == 1 and len(bucket) <= _TRUNCATED_BUCKET_MAX:
                matches[image] = candidates[0]
    return matches


def parse_takeout_date(data: bytes) -> "date | None":
    """photoTakenTime.timestamp (Sekunden, UTC) als Kalenderdatum; None bei allem Unerwarteten."""
    import json
    from datetime import UTC, date, datetime

    if len(data) > TAKEOUT_JSON_MAX_BYTES:
        return None
    try:
        document = json.loads(data.decode("utf-8"))
        raw = document["photoTakenTime"]["timestamp"]
        seconds = int(str(raw).strip())
        taken = datetime.fromtimestamp(seconds, UTC).date()
    except (ValueError, KeyError, TypeError, OverflowError, OSError, UnicodeDecodeError, AttributeError, RecursionError):
        return None
    if seconds <= 0 or taken < date(1826, 1, 1) or taken > datetime.now(UTC).date():
        return None
    return taken
