"""Länder-Geolocation als Risikosignal, vollständig lokal (Auth-Audit 7.2 «Neues Land»).

Quelle: DB-IP «IP to Country Lite» (https://db-ip.com, Lizenz CC BY 4.0, ohne Konto) als MMDB-Datei
unter ``GEOIP_DB_PATH``. Den Download und die monatliche Aktualisierung macht der Job
``geoip_update`` im job-worker (``update_database``); Backend und job-worker teilen sich dafür ein
Volume (Backend nur lesend). Übernommen wird eine neue Datei nur, wenn ihr SHA1 zur Prüfsumme auf der
offiziellen Download-Seite passt (DB-IP bietet keine Signatur) und sie die Plausibilitätsprüfung besteht.

Gespeichert wird nur der Ländercode (ISO 3166-1 alpha-2), nie die IP. Fehlt die Datei oder ist sie
unlesbar, liefert ``country_for`` None - das Signal entfällt still (Systemmonitor «nicht
eingerichtet», kein Alarm). Private, lokale und reservierte Adressen werden nicht nachgeschlagen.
"""
from __future__ import annotations

import gzip
import hashlib
import hmac
import ipaddress
import logging
import os
import re
import tempfile
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.core.config import settings

_logger = logging.getLogger(__name__)

DOWNLOAD_URL = "https://download.db-ip.com/free/dbip-country-lite-{month}.mmdb.gz"
# Offizielle Download-Seite: nennt je Ausgabe MD5 und SHA1 der ENTPACKTEN MMDB-Datei (eine Signatur
# bietet DB-IP nicht an). Die Seite liegt auf einem anderen Host als die Datei (db-ip.com vs.
# download.db-ip.com); übernommen wird eine Datei nur, wenn ihr SHA1 zur Seite passt.
CHECKSUM_PAGE_URL = "https://db-ip.com/db/download/ip-to-country-lite"
MAX_CHECKSUM_PAGE_BYTES = 2 * 1024 * 1024
_CHECKSUM_ENTRY = re.compile(
    r"SHA1SUM\s*</dt>\s*<dd[^>]*>\s*([0-9a-fA-F]{40})\s*</dd>"
    r"(?:(?!SHA1SUM).){0,4000}?"
    r"(https://download\.db-ip\.com/free/dbip-country-lite-\d{4}-\d{2}\.mmdb\.gz)",
    re.S,
)
USER_AGENT = "hocx-geoip-update"
ATTRIBUTION = "IP to Country Lite by DB-IP (https://db-ip.com), CC BY 4.0"
# Grenzen für den Download (die Datei hat ~5 MB gepackt, ~8 MB entpackt)
MAX_COMPRESSED_BYTES = 64 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
DOWNLOAD_TIMEOUT_SECONDS = 60
DOWNLOAD_DEADLINE_SECONDS = 300
# Plausibilitätsprüfung einer neuen Datei
MIN_NODE_COUNT = 10_000
MAX_AGE_DAYS = 120
SAMPLE_ADDRESSES = ("8.8.8.8", "1.1.1.1", "2001:4860:4860::8888")
_RELOAD_CHECK_SECONDS = 300
_CODE = re.compile(r"^[A-Z]{2}$")


class GeoIPUpdateError(Exception):
    """Download oder Prüfung der Datenbank gescheitert (der Job meldet das als Fehler)."""


@dataclass
class _State:
    reader: object | None = None
    mtime: float | None = None
    checked_at: float = 0.0


_state = _State()
_lock = threading.Lock()


def valid_code(value: str | None) -> str | None:
    """Ländercode normalisiert (zwei Grossbuchstaben) oder None."""
    if not value:
        return None
    code = value.strip().upper()
    return code if _CODE.match(code) else None


_NAMES_PATH = Path(__file__).with_name("country_names_generated.json")
_names: dict[str, dict[str, str]] | None = None


def country_name(code: str | None, lang: str) -> str | None:
    """Übersetzter Ländername (scripts/sync-country-names.mjs), sonst der Code selbst."""
    global _names
    code = valid_code(code)
    if code is None:
        return None
    if _names is None:
        import json

        try:
            _names = json.loads(_NAMES_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _names = {}
    from app.core.locale_config_generated import DEFAULT_LOCALE

    return (_names.get(lang) or _names.get(DEFAULT_LOCALE) or {}).get(code, code)


def _path() -> Path:
    return Path(settings.geoip_db_path)


def _open(path: Path):
    import maxminddb

    return maxminddb.open_database(str(path), maxminddb.MODE_AUTO)


def _reader():
    """Offener Leser; lädt die Datei neu, wenn der Job sie ersetzt hat (höchstens alle 5 min geprüft)."""
    now = time.monotonic()
    # Auch «keine Datei» gilt bis zur nächsten Prüfung (kein stat() je Anmeldung)
    if _state.checked_at and now - _state.checked_at < _RELOAD_CHECK_SECONDS:
        return _state.reader
    with _lock:
        if _state.checked_at and now - _state.checked_at < _RELOAD_CHECK_SECONDS:
            return _state.reader
        _state.checked_at = now
        path = _path()
        try:
            mtime = path.stat().st_mtime
        except OSError:
            _close_locked()
            return None
        if _state.reader is not None and mtime == _state.mtime:
            return _state.reader
        try:
            reader = _open(path)
        except Exception as exc:  # noqa: BLE001 - kaputte Datei: Signal entfällt, Monitor zeigt es
            _logger.warning("GeoIP-Datenbank nicht lesbar: %s", type(exc).__name__)
            _close_locked()
            return None
        _close_locked()
        _state.reader, _state.mtime = reader, mtime
        return reader


def _close_locked() -> None:
    if _state.reader is not None:
        try:
            _state.reader.close()
        except Exception:  # noqa: BLE001 - beim Schliessen egal
            pass
    _state.reader, _state.mtime = None, None


def reset() -> None:
    """Leser schliessen (Tests, nach einem Update im selben Prozess)."""
    with _lock:
        _close_locked()
        _state.checked_at = 0.0


def _lookup_code(reader, address: str) -> str | None:
    record = reader.get(address)
    if not isinstance(record, dict):
        return None
    country = record.get("country")
    if isinstance(country, dict):
        return valid_code(country.get("iso_code"))
    return None


def country_for(ip: str | None) -> str | None:
    """Ländercode der Adresse oder None (keine DB, private Adresse, kein Eintrag). Wirft nie."""
    if not ip:
        return None
    try:
        address = ipaddress.ip_address(ip.strip())
    except ValueError:
        return None
    if not address.is_global:
        return None
    reader = _reader()
    if reader is None:
        return None
    try:
        return _lookup_code(reader, str(address))
    except Exception:  # noqa: BLE001 - z. B. IPv6-Adresse in einer reinen IPv4-Datenbank
        return None


def status() -> dict:
    """Für Systemmonitor und Richtlinien-Seite: eingerichtet? Stand der Datei."""
    reader = _reader()
    if reader is None:
        return {"available": False, "auto_update": settings.geoip_auto_update}
    try:
        metadata = reader.metadata()
        built = datetime.fromtimestamp(int(metadata.build_epoch), UTC)
    except Exception:  # noqa: BLE001 - nur Anzeige
        return {"available": True, "auto_update": settings.geoip_auto_update}
    return {
        "available": True,
        "auto_update": settings.geoip_auto_update,
        "build_date": built.date().isoformat(),
        "age_days": max(0, (datetime.now(UTC) - built).days),
    }


# ── Aktualisierung (Job geoip_update) ─────────────────────────────────


def validate_file(path: Path, *, now: datetime | None = None) -> dict:
    """Prüft eine (neue) MMDB-Datei: Ländertyp, IPv6-Baum, Grösse, Alter, Stichproben. Wirft
    ``GeoIPUpdateError``, sonst Metadaten für den Job-Verlauf."""
    now = now or datetime.now(UTC)
    try:
        reader = _open(path)
    except Exception as exc:  # noqa: BLE001 - jede Lesefehlerart heisst «ungültig»
        raise GeoIPUpdateError(f"Datei nicht lesbar ({type(exc).__name__})") from exc
    try:
        metadata = reader.metadata()
        database_type = str(metadata.database_type or "")
        if "country" not in database_type.lower():
            raise GeoIPUpdateError(f"unerwarteter Datenbanktyp {database_type[:40]!r}")
        if int(metadata.ip_version) != 6:
            raise GeoIPUpdateError("Datenbank ohne IPv6")
        if int(metadata.node_count) < MIN_NODE_COUNT:
            raise GeoIPUpdateError("Datenbank zu klein")
        built = datetime.fromtimestamp(int(metadata.build_epoch), UTC)
        if built > now + timedelta(days=2) or built < now - timedelta(days=MAX_AGE_DAYS):
            raise GeoIPUpdateError(f"unplausibles Erstelldatum {built.date().isoformat()}")
        resolved = sum(1 for address in SAMPLE_ADDRESSES if _lookup_code(reader, address))
        if resolved < 2:
            raise GeoIPUpdateError("Stichproben ohne Land")
        return {"database_type": database_type[:40], "build_date": built.date().isoformat(), "nodes": int(metadata.node_count)}
    finally:
        reader.close()


def _months(now: datetime) -> list[str]:
    first = now.replace(day=1)
    previous = (first - timedelta(days=1)).replace(day=1)
    return [first.strftime("%Y-%m"), previous.strftime("%Y-%m")]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Weiterleitungen nie folgen (kein Umweg auf http:// oder interne Hosts)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102, PLR0913
        raise urllib.error.HTTPError(req.full_url, code, "Weiterleitung abgelehnt", headers, fp)


_opener = urllib.request.build_opener(_NoRedirect)


def _download(url: str, target: Path) -> None:
    """Gepackte Datei in Blöcken neben das Ziel laden (Grössenlimit, Gesamtdeadline), dann entpacken."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    packed = target.with_name(target.name + ".gz")
    deadline = time.monotonic() + DOWNLOAD_DEADLINE_SECONDS
    size = 0
    try:
        with _opener.open(request, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response, packed.open("wb") as sink:  # noqa: S310 - feste HTTPS-URL
            while True:
                if time.monotonic() > deadline:
                    raise GeoIPUpdateError("Download dauert zu lange")
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_COMPRESSED_BYTES:
                    raise GeoIPUpdateError("Download zu gross")
                sink.write(chunk)
        _unpack(packed, target)
    finally:
        packed.unlink(missing_ok=True)


def parse_checksums(page: str) -> dict[str, str]:
    """SHA1 der entpackten MMDB je Download-URL aus der Download-Seite (nur MMDB-Einträge)."""
    return {url: sha1.lower() for sha1, url in _CHECKSUM_ENTRY.findall(page)}


def _published_checksums() -> dict[str, str]:
    """Download-Seite laden (Grössenlimit, keine Weiterleitungen) und die Prüfsummen auslesen."""
    request = urllib.request.Request(CHECKSUM_PAGE_URL, headers={"User-Agent": USER_AGENT})
    try:
        with _opener.open(request, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:  # noqa: S310 - feste HTTPS-URL
            body = response.read(MAX_CHECKSUM_PAGE_BYTES + 1)
    except (urllib.error.URLError, OSError) as exc:
        raise GeoIPUpdateError(f"Prüfsummen nicht abrufbar ({type(exc).__name__})") from exc
    if len(body) > MAX_CHECKSUM_PAGE_BYTES:
        raise GeoIPUpdateError("Prüfsummen-Seite zu gross")
    return parse_checksums(body.decode("utf-8", errors="replace"))


def file_sha1(path: Path) -> str:
    digest = hashlib.sha1(usedforsecurity=False)  # Vergleichswert der Quelle ist SHA1
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _unpack(packed: Path, target: Path) -> None:
    written = 0
    try:
        with gzip.open(packed, "rb") as source, target.open("wb") as sink:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > MAX_UNCOMPRESSED_BYTES:
                    raise GeoIPUpdateError("entpackte Datei zu gross")
                sink.write(chunk)
    except (OSError, EOFError) as exc:
        raise GeoIPUpdateError(f"Archiv ungültig ({type(exc).__name__})") from exc


def _current_build_month(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        reader = _open(path)
        try:
            return datetime.fromtimestamp(int(reader.metadata().build_epoch), UTC).strftime("%Y-%m")
        finally:
            reader.close()
    except Exception:  # noqa: BLE001 - kaputte Datei wird ersetzt
        return None


def update_database(*, now: datetime | None = None, download=None, checksums=None) -> dict:
    """Lädt die Datenbank des laufenden Monats, falls die vorhandene älter ist (sonst nichts).
    Anfang Monat ist die neue Datei evtl. noch nicht veröffentlicht: dann bleibt die alte; fehlt
    jede Datei, wird die des Vormonats geladen. Ersetzt atomar und nur nach bestandener Prüfung:
    SHA1 wie auf der Download-Seite veröffentlicht (``checksums``, sonst ``_published_checksums``),
    danach ``validate_file``. Ohne veröffentlichte Prüfsumme wird eine Ausgabe nicht geladen."""
    if not settings.geoip_auto_update:
        return {"skipped": "disabled"}
    now = now or datetime.now(UTC)
    download = download or _download
    checksums = checksums or _published_checksums
    path = _path()
    current_month = _current_build_month(path)
    months = _months(now)
    if current_month is not None and current_month >= months[0]:
        return {"skipped": "current", "build_month": current_month}
    candidates = months if current_month is None or current_month < months[1] else months[:1]
    path.parent.mkdir(parents=True, exist_ok=True)
    published = checksums()
    last_error: str | None = None
    for month in candidates:
        url = DOWNLOAD_URL.format(month=month)
        expected = published.get(url)
        if expected is None:
            # Die Seite nennt nur die aktuelle Ausgabe: ohne Prüfsumme gilt der Monat als nicht verfügbar
            last_error = f"{month}: keine Prüfsumme veröffentlicht"
            continue
        handle, temp_name = tempfile.mkstemp(prefix=".geoip-", suffix=".mmdb", dir=path.parent)
        os.close(handle)
        temp = Path(temp_name)
        try:
            try:
                download(url, temp)
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    last_error = f"{month} noch nicht veröffentlicht"
                    continue
                raise GeoIPUpdateError(f"HTTP {exc.code}") from exc
            except (urllib.error.URLError, OSError) as exc:
                raise GeoIPUpdateError(f"Download fehlgeschlagen ({type(exc).__name__})") from exc
            if not hmac.compare_digest(file_sha1(temp), expected.lower()):
                raise GeoIPUpdateError(f"Prüfsumme passt nicht ({month})")
            info = validate_file(temp, now=now)
            os.chmod(temp, 0o640)
            os.replace(temp, path)
            reset()
            _logger.info("GeoIP-Datenbank aktualisiert (%s)", info.get("build_date"))
            return {"updated": month, "sha1": expected.lower(), **info}
        finally:
            temp.unlink(missing_ok=True)
    if current_month is not None:
        # Alte Datei bleibt; neue Ausgabe ist noch nicht da
        return {"skipped": "not_published", "build_month": current_month}
    raise GeoIPUpdateError(last_error or "keine Datenbank verfügbar")
