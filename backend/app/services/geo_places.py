"""Ortsdaten für Foto-Standorte laden (Migration 0260_photo_places, Job ``geo_places_update``).

Quellen (offline in Postgres, keine Koordinaten von Fotos verlassen den Server):

- **GeoNames** (https://www.geonames.org, CC BY 4.0): ``cities500`` weltweit (Orte ab 500
  Einwohnern, Hauptorte), dazu die Länderdateien aus ``GEO_PLACES_COUNTRIES`` (Standard CH, LI,
  AT, DE, FR, IT) für Weiler, Gipfel, Pässe, Hütten, Seen und Gletscher in der Nähe der Schweiz.
  Für CH nur die Ortschaften (mit Kantonskürzel) - die Geländenamen kommen aus swissNAMES3D.
  ``admin1CodesASCII`` liefert Kanton/Region. Ohne Prüfsumme der Quelle: geprüft werden
  ``Content-Length`` = geladene Bytes, ZIP-CRC, Mindestmenge und Schwund (SQL-Funktion);
  gespeichert wird unsere SHA-256.
- **swisstopo swissNAMES3D** (https://www.swisstopo.admin.ch, freie Geodaten OGD, Quellenangabe
  «© swisstopo»): neueste Ausgabe aus der STAC-API (``data.geo.admin.ch``), CSV in LV95; geprüft
  gegen die SHA-256 aus ``file:checksum`` der STAC-Antwort.

Ablauf: Download in ein Arbeitsverzeichnis (Grösse, Frist, keine Weiterleitungen, nur HTTPS zu
den zwei Hosts), Zeilen streamen und per ``COPY`` in die Zwischenablage ``geo_place_import``
schreiben, dann ``hocx_geo_import_apply`` (SECURITY DEFINER) übernimmt sie in ``geo_place``. Die
Laufzeitrolle kann ``geo_place`` selbst nicht ändern. Danach trägt der Job ``photo_places_resolve``
die Ortsnamen der Fotos nach (``geo_generation``).
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import math
import re
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine, make_url, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.core.config import settings

_logger = logging.getLogger(__name__)

USER_AGENT = "hocx-geo-places-update"
GEONAMES_BASE = "https://download.geonames.org/export/dump/"
SWISSNAMES_STAC = "https://data.geo.admin.ch/api/stac/v0.9/collections/ch.swisstopo.swissnames3d/items?limit=100"
ALLOWED_HOSTS = ("download.geonames.org", "data.geo.admin.ch")
ATTRIBUTION = {
    "geonames": "GeoNames (geonames.org), CC BY 4.0",
    "swissnames3d": "swissNAMES3D © swisstopo",
}

MAX_DOWNLOAD_BYTES = 256 * 1024 * 1024
MAX_UNPACKED_BYTES = 1024 * 1024 * 1024
DOWNLOAD_TIMEOUT_SECONDS = 60
DOWNLOAD_DEADLINE_SECONDS = 900
COPY_COLUMNS = (
    "place_key", "source", "kind", "name", "latitude", "longitude", "country_code", "admin1_code", "admin1_name",
    "population", "elevation_m", "importance", "names",
)
# Mindestmengen je Quelle (vollständige Dateien liefern ein Vielfaches); Tests/Fixtures setzen 1.
MIN_ROWS = {"geonames": 100_000, "swissnames3d": 100_000}
MAX_ALTERNATE_NAMES = 12
NEIGHBOUR_BONUS = 0.5
SWISS_BONUS = 1.0

LOCALITY_KINDS = ("city", "town", "village")
PRECISE_KINDS = ("hamlet", "district", "peak", "pass", "hut", "lake", "glacier", "poi", "station", "field")

# Grundgewicht je Art für die Rangfolge in der Ortssuche
_KIND_WEIGHT = {
    "city": 3.0, "town": 2.6, "village": 2.2, "region": 2.4, "lake": 2.0, "hut": 1.9, "peak": 1.8,
    "glacier": 1.8, "pass": 1.7, "district": 1.5, "station": 1.4, "hamlet": 1.2, "poi": 1.2, "field": 0.6,
}


class GeoPlacesError(Exception):
    """Download, Prüfung oder Import gescheitert (der Job meldet das als Fehler)."""


@dataclass
class PlaceRow:
    place_key: str
    source: str
    kind: str
    name: str
    latitude: float
    longitude: float
    country_code: str | None = None
    admin1_code: str | None = None
    admin1_name: str | None = None
    population: int = 0
    elevation_m: int | None = None
    importance: float = 0.0
    names: str = ""


def importance(kind: str, population: int = 0, country_code: str | None = None, *, major: bool = False) -> float:
    value = _KIND_WEIGHT.get(kind, 1.0) + min(1.5, math.log10(max(population, 0) + 1) / 4)
    if major:
        value += 0.4
    if country_code == "CH":
        value += SWISS_BONUS
    elif country_code in ("LI", "AT", "DE", "FR", "IT"):
        value += NEIGHBOUR_BONUS
    return round(min(value, 9.9), 3)


_LATIN = re.compile(r"^[0-9A-Za-zÀ-ɏ' .,()/-]+$")


def _names(primary: str, *others: str) -> str:
    """Alle Schreibweisen für die Suche (Lateinschrift, ohne Codes), höchstens 12 weitere."""
    seen: list[str] = []
    for value in (primary, *others):
        value = (value or "").strip()
        if not value or len(value) > 80 or not _LATIN.match(value) or value in seen:
            continue
        if value.isupper() and len(value) <= 4:  # Codes wie «ZRH», «CH0565»
            continue
        if any(char.isdigit() for char in value):
            continue
        seen.append(value)
        if len(seen) > MAX_ALTERNATE_NAMES:
            break
    return " | ".join(seen)[:4000]


def _clean_text(value: str | None, limit: int) -> str | None:
    value = (value or "").strip()
    return value[:limit] if value else None


# --- GeoNames -----------------------------------------------------------------------------------

_SKIP_PPL = {"PPLH", "PPLQ", "PPLW", "PPLCH", "PPLR"}
_PEAK = {"PK", "PKS", "MT", "MTS", "HLL", "HLLS"}
_LAKE = {"LK", "LKS", "LKN", "RSV"}


def geonames_kind(feature_class: str, feature_code: str, population: int) -> str | None:
    if feature_class == "P":
        if feature_code in _SKIP_PPL:
            return None
        if feature_code == "PPLX":
            return "district"
        if feature_code in ("PPLL", "PPLF", "PPLS"):
            return "hamlet"
        if population >= 50_000 or feature_code == "PPLC":
            return "city"
        if population >= 10_000:
            return "town"
        if population >= 500 or feature_code.startswith("PPLA"):
            return "village"
        return "village" if population >= 200 else "hamlet"
    if feature_class == "T":
        if feature_code in _PEAK:
            return "peak"
        if feature_code == "PASS":
            return "pass"
        return None
    if feature_class == "S" and feature_code in ("HUT", "HUTS"):
        return "hut"
    if feature_class == "H":
        if feature_code in _LAKE:
            return "lake"
        if feature_code == "GLCR":
            return "glacier"
    return None


def parse_admin1(lines: Iterable[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in lines:
        parts = line.rstrip("\n").split("\t")
        if len(parts) >= 2 and parts[0] and parts[1]:
            result[parts[0]] = parts[1][:200]
    return result


def parse_geonames(lines: Iterable[str], admin1: dict[str, str], *, only_populated: bool = False) -> Iterator[PlaceRow]:
    """Zeilen im GeoNames-Dump-Format (19 Spalten, Tab) - cities500 und Länderdateien."""
    for line in lines:
        parts = line.rstrip("\n").split("\t")
        if len(parts) < 19 or not parts[0].isdigit():
            continue
        feature_class, feature_code = parts[6], parts[7]
        if only_populated and feature_class != "P":
            continue
        try:
            population = max(0, int(parts[14] or 0))
            latitude, longitude = float(parts[4]), float(parts[5])
        except ValueError:
            continue
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            continue
        kind = geonames_kind(feature_class, feature_code, population)
        name = _clean_text(parts[1], 200)
        if kind is None or name is None:
            continue
        country = parts[8].strip().upper() if re.fullmatch(r"[A-Za-z]{2}", parts[8].strip()) else None
        admin_code = _clean_text(parts[10], 20)
        elevation = parts[15] or parts[16]
        try:
            elevation_m = int(elevation) if elevation and int(elevation) > -1000 else None
        except ValueError:
            elevation_m = None
        alternates = parts[3].split(",") if parts[3] else []
        yield PlaceRow(
            place_key=f"gn:{parts[0]}",
            source="geonames",
            kind=kind,
            name=name,
            latitude=round(latitude, 6),
            longitude=round(longitude, 6),
            country_code=country,
            # Schweiz: Kantonskürzel (GeoNames nutzt BE, ZH …), sonst der Code der Region
            admin1_code=admin_code,
            admin1_name=admin1.get(f"{country}.{admin_code}") if country and admin_code else None,
            population=population,
            elevation_m=elevation_m,
            importance=importance(kind, population, country, major=feature_code in ("PPLC", "PPLA")),
            names=_names(name, parts[2], *alternates),
        )


# --- swissNAMES3D -------------------------------------------------------------------------------

_HUT_NAME = re.compile(r"(h(ü|ue)tte|cabane|capanna|rifugio|chamanna|biwak|bivacco|bivouac|refuge|chalet|buvette)", re.I)
_PKT_KINDS = {
    "Hauptgipfel": "peak", "Gipfel": "peak", "Alpiner Gipfel": "peak", "Huegel": "peak", "Haupthuegel": "peak",
    "Felskopf": "peak", "Pass": "pass", "Strassenpass": "pass", "Aussichtspunkt": "poi", "Wasserfall": "poi",
    "Grotte, Hoehle": "poi", "Kapelle": "poi", "Turm": "poi", "Erratischer Block": "poi", "Quelle": "poi",
    "Denkmal": "poi", "Sakrales Gebaeude": "poi", "Haltestelle Bahn": "station", "Haltestelle Schiff": "station",
    "Uebrige Bahnen": "station", "Quartier": "district", "Ortsteil": "district", "Flurname swisstopo": "field",
    "Lokalname swisstopo": "field",
}
_PLY_KINDS = {
    "See": "lake", "Seeteil": "lake", "Gletscher": "glacier", "Landschaftsname": "region", "Grossregion": "region",
    "Massiv": "region", "Haupttal": "region",
}
_SMALL_SETTLEMENT = {"< 20", "20 bis 49", "50 bis 99"}
_MAJOR_PEAK = {"Hauptgipfel", "Alpiner Gipfel"}


def lv95_to_wgs84(east: float, north: float) -> tuple[float, float]:
    """LV95 (EPSG:2056) → WGS84 mit den Näherungsformeln von swisstopo (Genauigkeit ~1 m)."""
    y = (east - 2_600_000) / 1_000_000
    x = (north - 1_200_000) / 1_000_000
    lon = 2.6779094 + 4.728982 * y + 0.791484 * y * x + 0.1306 * y * x * x - 0.0436 * y ** 3
    lat = 16.9023892 + 3.238272 * x - 0.270978 * y * y - 0.002528 * x * x - 0.0447 * y * y * x - 0.0140 * x ** 3
    return round(lat * 100 / 36, 6), round(lon * 100 / 36, 6)


def swissnames_kind(table: str, row: dict[str, str]) -> str | None:
    art = row.get("OBJEKTART", "")
    if table == "PLY":
        return _PLY_KINDS.get(art)
    if art == "Ort":
        return "hamlet" if row.get("EINWOHNERKATEGORIE") in _SMALL_SETTLEMENT else None
    if art == "Gebaeude":
        use = row.get("GEBAEUDENUTZUNG", "")
        if use in ("Gasthof abgelegen", "Schutzhuette"):
            return "hut"
        if use == "k_W":
            return "hut" if _HUT_NAME.search(row.get("NAME", "")) else None
        if use in ("Stadion", "Observatorium", "Aussichtsturm"):
            return "poi"
        return None
    return _PKT_KINDS.get(art)


def parse_swissnames(tables: Iterable[tuple[str, Iterable[str]]]) -> Iterator[PlaceRow]:
    """CSV-Tabellen (``PKT``/``PLY``, Semikolon, UTF-8) - mehrere Sprachen je Objekt zusammengefasst."""
    for table, lines in tables:
        objects: dict[str, PlaceRow] = {}
        alternates: dict[str, list[str]] = {}
        for row in csv.DictReader(lines, delimiter=";"):
            kind = swissnames_kind(table, row)
            uuid_value = (row.get("UUID") or "").strip("{} ")
            name = _clean_text(row.get("NAME"), 200)
            if kind is None or not name or not re.fullmatch(r"[0-9A-Fa-f-]{36}", uuid_value):
                continue
            key = f"sn:{uuid_value.lower()}"
            if key in objects:
                alternates[key].append(name)
                continue
            try:
                east, north = float(row.get("E") or ""), float(row.get("N") or "")
            except ValueError:
                continue
            if not (2_400_000 < east < 2_900_000 and 1_000_000 < north < 1_400_000):
                continue
            latitude, longitude = lv95_to_wgs84(east, north)
            try:
                elevation = round(float(row.get("Z") or row.get("HOEHE") or ""))
            except ValueError:
                elevation = None
            objects[key] = PlaceRow(
                place_key=key, source="swissnames3d", kind=kind, name=name, latitude=latitude, longitude=longitude,
                country_code="CH", elevation_m=elevation,
                importance=importance(kind, 0, "CH", major=row.get("OBJEKTART") in _MAJOR_PEAK),
            )
            alternates[key] = []
        for key, place in objects.items():
            place.names = _names(place.name, *alternates[key])
            yield place


# --- Zwischenablage und Übernahme ---------------------------------------------------------------


def stage(db: Session, rows: Iterable[PlaceRow], source: str) -> int:
    """Leert die Zwischenablage der Quelle und schreibt die Zeilen per COPY (gebundene Werte)."""
    db.execute(text("DELETE FROM geo_place_import WHERE source = :source"), {"source": source})
    connection = db.connection().connection.driver_connection
    count = 0
    seen: set[str] = set()
    with connection.cursor() as cursor:
        with cursor.copy(f"COPY geo_place_import ({', '.join(COPY_COLUMNS)}) FROM STDIN") as copy:  # sql-ok: feste Spaltenliste
            for row in rows:
                if row.source != source or row.place_key in seen:
                    continue
                seen.add(row.place_key)
                copy.write_row(tuple(getattr(row, column) for column in COPY_COLUMNS))
                count += 1
    return count


def apply(db: Session, source: str, *, version: str, sha256: str | None, size: int | None, min_rows: int | None = None) -> dict:
    result = db.execute(
        text("SELECT public.hocx_geo_import_apply(:source, :version, :sha, :bytes, :min_rows)"),
        {"source": source, "version": version, "sha": sha256, "bytes": size, "min_rows": MIN_ROWS[source] if min_rows is None else min_rows},
    ).scalar_one()
    return dict(result or {})


def import_geonames_files(
    db: Session, *, cities: Path, admin1: Path, countries: dict[str, Path], version: str, sha256: str | None = None,
    size: int | None = None, min_rows: int | None = None,
) -> dict:
    """GeoNames aus lokalen Dateien (ZIP oder TXT) importieren; committet."""
    admin_names = parse_admin1(_text_lines(admin1))

    def rows() -> Iterator[PlaceRow]:
        yield from parse_geonames(_text_lines(cities), admin_names)
        for country, path in countries.items():
            yield from parse_geonames(_text_lines(path), admin_names, only_populated=country == "CH")

    staged = stage(db, rows(), "geonames")
    result = apply(db, "geonames", version=version, sha256=sha256, size=size, min_rows=min_rows)
    db.commit()
    return {"source": "geonames", "rows": staged, **result}


def import_swissnames_file(
    db: Session, archive: Path, *, version: str, sha256: str | None = None, size: int | None = None, min_rows: int | None = None,
) -> dict:
    """swissNAMES3D aus dem CSV-ZIP (oder einem Ordner mit den CSV-Tabellen, Tests/E2E); committet."""
    if archive.is_dir():
        handles = []
        try:
            tables = []
            for table in ("PKT", "PLY"):
                path = next((p for p in archive.iterdir() if p.name.upper().endswith(f"_{table}.CSV")), None)
                if path is None:
                    raise GeoPlacesError(f"swissNAMES3D ohne Tabelle {table}")
                handle = path.open(encoding="utf-8-sig", newline="")
                handles.append(handle)
                tables.append((table, handle))
            staged = stage(db, parse_swissnames(tables), "swissnames3d")
        finally:
            for handle in handles:
                handle.close()
    else:
        with zipfile.ZipFile(archive) as bundle:
            names = {Path(info.filename).name: info for info in bundle.infolist()}
            tables = []
            for table in ("PKT", "PLY"):
                info = next((info for name, info in names.items() if name.upper().endswith(f"_{table}.CSV")), None)
                if info is None:
                    raise GeoPlacesError(f"swissNAMES3D ohne Tabelle {table}")
                if info.file_size > MAX_UNPACKED_BYTES:
                    raise GeoPlacesError("swissNAMES3D-Tabelle zu gross")
                tables.append((table, io.TextIOWrapper(bundle.open(info), encoding="utf-8-sig", newline="")))
            staged = stage(db, parse_swissnames(tables), "swissnames3d")
    result = apply(db, "swissnames3d", version=version, sha256=sha256, size=size, min_rows=min_rows)
    db.commit()
    return {"source": "swissnames3d", "rows": staged, **result}


def _text_lines(path: Path) -> Iterator[str]:
    """Zeilen einer TXT-Datei oder der ersten TXT im ZIP (ohne readme)."""
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as bundle:
            info = next(
                (info for info in bundle.infolist() if info.filename.lower().endswith(".txt") and "readme" not in info.filename.lower()),
                None,
            )
            if info is None:
                raise GeoPlacesError(f"{path.name}: keine Textdatei im ZIP")
            if info.file_size > MAX_UNPACKED_BYTES:
                raise GeoPlacesError(f"{path.name}: zu gross")
            with bundle.open(info) as raw:
                yield from io.TextIOWrapper(raw, encoding="utf-8")
        return
    with path.open(encoding="utf-8") as handle:
        yield from handle


# --- Download ------------------------------------------------------------------------------------


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102, PLR0913
        raise urllib.error.HTTPError(req.full_url, code, "Weiterleitung abgelehnt", headers, fp)


_opener = urllib.request.build_opener(_NoRedirect)


def _check_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise GeoPlacesError("Quelle nicht erlaubt")


def _request(url: str, method: str = "GET") -> urllib.request.Request:
    _check_url(url)
    return urllib.request.Request(url, method=method, headers={"User-Agent": USER_AGENT})


def download(url: str, target: Path) -> tuple[int, str]:
    """Datei laden (Grösse, Frist, Content-Length muss stimmen); (Bytes, SHA-256)."""
    deadline = time.monotonic() + DOWNLOAD_DEADLINE_SECONDS
    digest = hashlib.sha256()
    size = 0
    try:
        with _opener.open(_request(url), timeout=DOWNLOAD_TIMEOUT_SECONDS) as response, target.open("wb") as sink:  # noqa: S310 - nur erlaubte HTTPS-Hosts
            expected = response.headers.get("Content-Length")
            while True:
                if time.monotonic() > deadline:
                    raise GeoPlacesError("Download dauert zu lange")
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_DOWNLOAD_BYTES:
                    raise GeoPlacesError("Download zu gross")
                digest.update(chunk)
                sink.write(chunk)
    except urllib.error.HTTPError as exc:
        raise GeoPlacesError(f"HTTP {exc.code}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise GeoPlacesError(f"Download fehlgeschlagen ({type(exc).__name__})") from exc
    if expected is not None and expected.isdigit() and int(expected) != size:
        raise GeoPlacesError("Download unvollständig")
    if zipfile.is_zipfile(target):
        with zipfile.ZipFile(target) as bundle:
            if bundle.testzip() is not None:
                raise GeoPlacesError("ZIP beschädigt")
    return size, digest.hexdigest()


def _head_last_modified(url: str) -> str:
    try:
        with _opener.open(_request(url, "HEAD"), timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:  # noqa: S310 - erlaubter Host
            return response.headers.get("Last-Modified") or ""
    except (urllib.error.URLError, OSError) as exc:
        raise GeoPlacesError(f"Quelle nicht erreichbar ({type(exc).__name__})") from exc


def latest_swissnames_asset() -> tuple[str, str, str]:
    """(Ausgabe, URL, SHA-256) der neuesten CSV-Ausgabe laut STAC."""
    try:
        with _opener.open(_request(SWISSNAMES_STAC), timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:  # noqa: S310 - erlaubter Host
            payload = json.loads(response.read(4 * 1024 * 1024))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise GeoPlacesError(f"swissNAMES3D-Katalog nicht lesbar ({type(exc).__name__})") from exc
    best: tuple[str, str, str] | None = None
    for feature in payload.get("features", []) if isinstance(payload, dict) else []:
        item = str(feature.get("id") or "")
        if not re.fullmatch(r"swissnames3d_\d{4}", item):
            continue
        for asset in (feature.get("assets") or {}).values():
            href = str(asset.get("href") or "")
            checksum = str(asset.get("file:checksum") or asset.get("checksum:multihash") or "")
            if not href.endswith("_2056.csv.zip") or not re.fullmatch(r"1220[0-9a-fA-F]{64}", checksum):
                continue
            if best is None or item > best[0]:
                best = (item, href, checksum[4:].lower())
    if best is None:
        raise GeoPlacesError("swissNAMES3D: keine CSV-Ausgabe gefunden")
    _check_url(best[1])
    return best


def _work_dir() -> Path:
    base = Path(settings.storage_work_root)
    try:
        base.mkdir(parents=True, exist_ok=True)
        return base
    except OSError:
        return Path(tempfile.gettempdir())


def _dataset(db: Session) -> dict[str, dict]:
    return {
        row.source: {"version": row.version, "imported_at": row.imported_at}
        for row in db.execute(text("SELECT source, version, imported_at FROM geo_dataset"))
    }


_geo_engine = None


def geo_session(*, allow_owner: bool = False) -> Session:
    """Session mit der Import-Rolle hocx_geo (GEO_DATABASE_URL). Nur sie darf in die Zwischenablage
    schreiben und hocx_geo_import_apply ausführen; hocx_app nicht. Ohne GEO_DATABASE_URL: die
    Owner-URL (DATABASE_URL) nur ausserhalb der Produktion bzw. für das vom Betrieb gestartete
    Skript scripts/import_geo_places.py (allow_owner)."""
    global _geo_engine
    url = settings.geo_database_url
    if not url:
        if not (allow_owner or not settings.is_production):
            raise GeoPlacesError("GEO_DATABASE_URL fehlt (DB-Rolle hocx_geo, Migration 0260)")
        url = settings.database_url
    if _geo_engine is None or str(_geo_engine.url) != str(make_url(url)):
        if _geo_engine is not None:
            _geo_engine.dispose()
        _geo_engine = create_engine(
            url, future=True, pool_pre_ping=True, hide_parameters=True, poolclass=NullPool,
            connect_args={"application_name": f"hocx-{settings.process_kind}-geo"},
        )
    return Session(bind=_geo_engine, autoflush=False, future=True)


def update_places(_db: Session | None = None, *, now: datetime | None = None) -> dict:
    """Job geo_places_update: lädt neue Ausgaben, sonst nichts. Fehler einer Quelle brechen ab.
    Schreibt nur über die Import-Rolle hocx_geo (geo_session), nie mit der Session des Loops."""
    if not settings.geo_places_auto_update:
        return {"skipped": "disabled"}
    with geo_session() as db:
        return _update_places(db, now=now)


def _update_places(db: Session, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    current = _dataset(db)
    db.commit()
    result: dict = {}
    with tempfile.TemporaryDirectory(prefix="geo-places-", dir=_work_dir()) as work:
        folder = Path(work)
        geonames = current.get("geonames")
        if geonames is None or geonames["imported_at"] < now - timedelta(days=settings.geo_places_max_age_days):
            countries = [code.strip().upper() for code in settings.geo_places_countries.split(",") if re.fullmatch(r"\s*[A-Za-z]{2}\s*", code)]
            total, digests, files = 0, hashlib.sha256(), {}
            for name in ("cities500.zip", "admin1CodesASCII.txt", *[f"{code}.zip" for code in countries]):
                size, sha = download(GEONAMES_BASE + name, folder / name)
                total += size
                digests.update(sha.encode())
                files[name] = folder / name
            version = _head_last_modified(GEONAMES_BASE + "cities500.zip") or now.date().isoformat()
            result["geonames"] = import_geonames_files(
                db, cities=files["cities500.zip"], admin1=files["admin1CodesASCII.txt"],
                countries={code: files[f"{code}.zip"] for code in countries}, version=version,
                sha256=digests.hexdigest(), size=total,
            )
            for path in files.values():
                path.unlink(missing_ok=True)
        else:
            result["geonames"] = "current"
        edition, url, expected_sha = latest_swissnames_asset()
        swiss = current.get("swissnames3d")
        if swiss is None or swiss["version"] != edition:
            target = folder / "swissnames3d.csv.zip"
            size, sha = download(url, target)
            if sha != expected_sha:
                raise GeoPlacesError("swissNAMES3D: Prüfsumme stimmt nicht")
            result["swissnames3d"] = import_swissnames_file(db, target, version=edition, sha256=sha, size=size)
        else:
            result["swissnames3d"] = "current"
    _logger.info("Ortsdaten: %s", result)
    return result


def status(db: Session) -> list[dict]:
    """Stand je Quelle für die Quellenangabe in der Oberfläche."""
    return [
        {
            "source": row.source, "version": row.version, "imported_at": row.imported_at, "rows": row.row_count,
            "attribution": ATTRIBUTION.get(row.source, row.source),
        }
        for row in db.execute(text("SELECT source, version, imported_at, row_count FROM geo_dataset ORDER BY source"))
    ]
