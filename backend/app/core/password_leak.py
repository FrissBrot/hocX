"""Prüfung neuer Passwörter auf bekannte Leaks (SEC-AUTH-015, NIST 800-63B §3.1.1.2).

Ablauf (``PASSWORD_LEAK_CHECK``):

- ``on`` (Standard): SHA-1 des Passworts lokal berechnen, nur die ersten **5 Hex-Zeichen** gehen an
  die Range-API von «Have I Been Pwned» (``https://api.pwnedpasswords.com/range/<prefix>``,
  k-Anonymität). Die Antwort enthält alle bekannten Suffixe dieses Präfixes mit Zählwert; der
  Vergleich passiert nur hier. ``Add-Padding: true`` lässt HIBP die Antwort mit Fülleinträgen
  (Zählwert 0) auf eine einheitliche Grösse auffüllen - die Grösse verrät dann nichts über den
  Präfix; Fülleinträge werden ignoriert. Kurzes Timeout, eigener User-Agent ohne Personen- oder
  Projektangaben. Die Antwort (nur Suffixe mit Zählwert > 0) liegt eine Stunde im Redis-Cache je
  Präfix. Nicht erreichbar → lokale Liste.
- ``local-only``: nur die lokale Liste (``leaked_passwords.bin``, erzeugt von
  ``scripts/build-leaked-password-list.py`` aus SecLists, MIT).
- ``off``: keine Leak-Prüfung.

Fehlen HIBP und Liste, wird das Passwort angenommen (nie Login/Reset blockieren), mit Warnung im
Log und Zähler für den Systemmonitor (``status()``). Passwörter, Hashes und Suffixe werden nie
geloggt oder gespeichert.
"""
from __future__ import annotations

import bisect
import hashlib
import hmac
import logging
import struct
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings

_logger = logging.getLogger(__name__)

API_URL = "https://api.pwnedpasswords.com/range/"
USER_AGENT = "hocx-password-check"
CACHE_PREFIX = "pwned:range:"
CACHE_SECONDS = 3600
STATUS_KEY = "pwned:status"
UNCHECKED_KEY = "pwned:unchecked"
# Eine gepaddete Antwort hat ~800-1000 Zeilen à ~40 Zeichen; mehr ist nie nötig.
MAX_RESPONSE_BYTES = 512 * 1024
LIST_PATH = Path(__file__).with_name("leaked_passwords.bin")
_MAGIC = b"HXLP1\n"

MODES = ("on", "off", "local-only")


@dataclass(frozen=True)
class LeakResult:
    leaked: bool
    # "hibp", "local" oder "none" (ungeprüft)
    source: str
    count: int | None = None


class LeakServiceUnavailable(Exception):
    """HIBP nicht erreichbar, Zeitüberschreitung oder unerwartete Antwort."""


def mode() -> str:
    value = (settings.password_leak_check or "on").strip().lower()
    return value if value in MODES else "on"


# ── Lokale Liste ────────────────────────────────────────────────────────


class _LocalList:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._loaded = False
        self._lock = threading.Lock()
        self._data = b""
        self._width = 0
        self._count = 0

    def _load(self) -> None:
        # Unter Lock und erst danach als geladen markiert: ein paralleler Aufruf sieht nie eine
        # halb geladene (leere) Liste und nimmt ein Passwort deshalb nie ungeprüft an.
        with self._lock:
            if not self._loaded:
                self._read()
                self._loaded = True

    def _read(self) -> None:
        try:
            raw = self.path.read_bytes()
        except OSError:
            _logger.warning("Lokale Leak-Liste fehlt (%s)", self.path.name)
            return
        header = len(_MAGIC) + 5
        if not raw.startswith(_MAGIC) or len(raw) < header:
            _logger.warning("Lokale Leak-Liste unlesbar (%s)", self.path.name)
            return
        count, width = struct.unpack(">IB", raw[len(_MAGIC):header])
        if width < 4 or width > 20 or len(raw) != header + count * width:
            _logger.warning("Lokale Leak-Liste unvollständig (%s)", self.path.name)
            return
        self._data, self._width, self._count = raw[header:], width, count

    @property
    def available(self) -> bool:
        if not self._loaded:
            self._load()
        return self._count > 0

    @property
    def count(self) -> int:
        return self._count if self.available else 0

    def _item(self, index: int) -> bytes:
        return self._data[index * self._width:(index + 1) * self._width]

    def contains(self, digest: bytes) -> bool:
        if not self.available:
            return False
        needle = digest[:self._width]
        position = bisect.bisect_left(range(self._count), needle, key=self._item)
        return position < self._count and self._item(position) == needle


_local = _LocalList(LIST_PATH)


def local_list_available() -> bool:
    return _local.available


# ── HIBP ────────────────────────────────────────────────────────────────


def _redis():
    try:
        from app.core.redis_client import get_redis_sync

        return get_redis_sync()
    except Exception:  # noqa: BLE001 - ohne Redis kein Cache, die Prüfung läuft trotzdem
        return None


def _parse_range(body: str) -> dict[str, int]:
    """``SUFFIX:COUNT``-Zeilen → {Suffix: Zählwert}; Fülleinträge (Zählwert 0) fallen weg."""
    found: dict[str, int] = {}
    for line in body.splitlines():
        suffix, _, count_text = line.strip().partition(":")
        if len(suffix) != 35:
            continue
        try:
            count = int(count_text)
        except ValueError:
            continue
        if count > 0:
            found[suffix.upper()] = count
    return found


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Weiterleitungen nie folgen (kein Umweg auf http:// oder interne Hosts)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102, PLR0913
        raise urllib.error.HTTPError(req.full_url, code, "Weiterleitung abgelehnt", headers, fp)


_opener = urllib.request.build_opener(_NoRedirect)


def _cache_key(prefix: str) -> str:
    """Redis-Schlüssel ohne Klartext-Präfix (Security-Review L2): wer Redis liest, erfährt nicht,
    welche Hash-Präfixe zuletzt geprüft wurden."""
    secret = (settings.auth_secret or "hocx").encode()
    return CACHE_PREFIX + hmac.new(secret, prefix.encode(), hashlib.sha256).hexdigest()[:32]


def _fetch_range(prefix: str) -> dict[str, int]:
    request = urllib.request.Request(
        API_URL + prefix, headers={"User-Agent": USER_AGENT, "Add-Padding": "true", "Accept": "text/plain"},
    )
    timeout = max(0.2, float(settings.password_leak_timeout_seconds))
    deadline = time.monotonic() + timeout
    try:
        with _opener.open(request, timeout=timeout) as response:  # noqa: S310 - feste HTTPS-URL, ohne Weiterleitungen
            if response.status != 200:
                raise LeakServiceUnavailable(f"HTTP {response.status}")
            chunks: list[bytes] = []
            size = 0
            while True:
                if time.monotonic() > deadline:
                    raise LeakServiceUnavailable("Zeitüberschreitung")
                chunk = response.read(16 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_RESPONSE_BYTES:
                    raise LeakServiceUnavailable("Antwort zu gross")
                chunks.append(chunk)
    except LeakServiceUnavailable:
        raise
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise LeakServiceUnavailable(type(exc).__name__) from exc
    found = _parse_range(b"".join(chunks).decode("ascii", "replace"))
    if not found:
        # Jede echte Range enthält Hunderte Einträge - leer heisst kaputte Antwort, nicht «sauber».
        raise LeakServiceUnavailable("leere Antwort")
    return found


def _range(prefix: str) -> dict[str, int]:
    client = _redis()
    key = _cache_key(prefix)
    if client is not None:
        try:
            cached = client.get(key)
            if cached is not None:
                found = _parse_range(cached.decode() if isinstance(cached, bytes) else cached)
                # Leerer/kaputter Eintrag = Cache-Miss (nie «sauber» aus einem kaputten Cache)
                if found:
                    return found
        except Exception:  # noqa: BLE001 - Cache ist optional
            client = None
    found = _fetch_range(prefix)
    if client is not None:
        try:
            client.set(key, "\n".join(f"{suffix}:{count}" for suffix, count in found.items()), ex=CACHE_SECONDS)
        except Exception:  # noqa: BLE001 - Cache ist optional
            pass
    return found


def _note(field: str) -> None:
    client = _redis()
    if client is None:
        return
    try:
        client.hset(STATUS_KEY, field, int(time.time()))
        client.expire(STATUS_KEY, 30 * 24 * 3600)
    except Exception:  # noqa: BLE001 - nur Statusanzeige
        pass


def _note_unchecked() -> None:
    client = _redis()
    if client is None:
        return
    try:
        client.incr(UNCHECKED_KEY)
        client.expire(UNCHECKED_KEY, 24 * 3600, nx=True)
    except Exception:  # noqa: BLE001 - nur Statusanzeige
        pass


# ── Einstieg ────────────────────────────────────────────────────────────


def check_password(password: str) -> LeakResult:
    """Ist das Passwort in einem bekannten Leak? Wirft nie."""
    current = mode()
    if current == "off" or not password:
        return LeakResult(leaked=False, source="none")
    digest = hashlib.sha1(password.encode("utf-8")).digest()  # noqa: S324 - HIBP-Format, kein Passwort-Hash
    if current == "on":
        hexdigest = digest.hex().upper()
        try:
            found = _range(hexdigest[:5])
        except LeakServiceUnavailable as exc:
            _note("last_failure")
            _logger.warning("HIBP-Range-API nicht verfügbar (%s), Rückfall auf lokale Liste", exc)
        except Exception as exc:  # noqa: BLE001 - nie den Passwortwechsel blockieren
            _note("last_failure")
            _logger.warning("Leak-Prüfung fehlgeschlagen (%s), Rückfall auf lokale Liste", type(exc).__name__)
        else:
            _note("last_success")
            count = found.get(hexdigest[5:], 0)
            return LeakResult(leaked=count >= max(1, settings.password_leak_min_count), source="hibp", count=count)
    if _local.available:
        return LeakResult(leaked=_local.contains(digest), source="local")
    _note_unchecked()
    _logger.warning("Leak-Prüfung nicht möglich (weder HIBP noch lokale Liste) - Passwort ungeprüft angenommen")
    return LeakResult(leaked=False, source="none")


def status() -> dict:
    """Für den Systemmonitor: Modus, lokale Liste, letzte Erfolge/Fehler, ungeprüfte Passwörter (24 h)."""
    last_success = last_failure = None
    unchecked = 0
    client = _redis()
    if client is not None:
        try:
            values = client.hgetall(STATUS_KEY) or {}
            decoded = {(k.decode() if isinstance(k, bytes) else k): int(v) for k, v in values.items()}
            last_success, last_failure = decoded.get("last_success"), decoded.get("last_failure")
            unchecked = int(client.get(UNCHECKED_KEY) or 0)
        except Exception:  # noqa: BLE001 - nur Statusanzeige
            pass
    return {
        "mode": mode(),
        "local_list": _local.available,
        "local_entries": _local.count,
        "last_success": last_success,
        "last_failure": last_failure,
        "unchecked_24h": unchecked,
    }
