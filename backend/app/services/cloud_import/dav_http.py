"""WebDAV mit Adresse vom Verein (kDrive, Nextcloud, SwissDisk …) - strenger SSRF-Schutz (Plan §10.1, E-9).

Anders als bei Microsoft/Google/Dropbox gibt es hier keine feste Host-Allowlist: die Adresse tippt
der Verein ein. Deshalb gilt für **jede** Verbindung (auch nach einem Redirect):

- Schema ``https`` (``http`` nur im Fake-Testmodus, und dann nur über den nachgebauten Transport;
  ``RealDavTransport`` verbindet nie unverschlüsselt). Keine Zugangsdaten, Query oder Fragment in
  der Adresse.
- Port nur aus ``ALLOWED_PORTS`` (443, 8443).
- Hostname statt IP-Literal (auch keine Kurzformen wie ``2130706433`` oder ``0x7f.1``: die letzte
  Label muss mit einem Buchstaben beginnen), keine internen Namen (``localhost``, ``*.local``,
  ``*.internal``, ``*.home.arpa`` …).
- DNS-Auflösung vor dem Verbinden; ist *eine* Adresse nicht öffentlich (privat, Loopback,
  Link-Local/Metadaten, CGNAT, Multicast, reserviert, IPv6-Pendants inkl. NAT64/6to4/Teredo,
  ``http.ip_is_public``), wird nicht verbunden. Verbunden wird mit genau der geprüften Adresse
  (kein zweites Auflösen → kein DNS-Rebinding); TLS mit SNI und Zertifikatsprüfung auf den Namen.
- Redirects folgt der Client nie automatisch: höchstens ``MAX_REDIRECTS``, jedes Ziel wird wie oben
  geprüft. Zugangsdaten (Basic-Auth) gehen nur an den Ursprung der Verbindung (Schema, Host, Port);
  PROPFIND folgt nur Redirects auf denselben Ursprung.
- Antwortgrössen begrenzt (PROPFIND ``MAX_PROPFIND_BYTES``, Fehlerkörper 64 KiB, Downloads am Strom
  gemessen), Zeitlimits je Verbindung (10 s Aufbau, 60 s Lese-Inaktivität) und insgesamt je Anfrage.
- PROPFIND-XML wird mit expat ohne DTD gelesen: jede ``<!DOCTYPE``-Deklaration (und damit jede
  Entität, XXE, «Billion Laughs») bricht ab, Verschachtelungstiefe und Elementzahl sind begrenzt.
- Passwort und Basic-Header erscheinen nie in Logs, Ausnahmetexten oder ``repr``.
"""

from __future__ import annotations

import base64
import hashlib
import http.client
import ipaddress
import json
import logging
import re
import socket
import ssl
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Protocol
from urllib.parse import quote, unquote, urljoin, urlsplit
from xml.parsers import expat

from app.services.cloud_import.fake_http import FakeTransport
from app.services.cloud_import.http import (
    CHUNK,
    CONNECT_TIMEOUT,
    READ_TIMEOUT,
    DownloadResult,
    DownloadTooLarge,
    HostNotAllowed,
    HttpResponse,
    ProviderError,
    ProviderThrottled,
    ProviderUnauthorized,
    RawResponse,
    ip_is_public,
    parse_retry_after,
    user_agent,
)

_logger = logging.getLogger(__name__)

ALLOWED_PORTS = frozenset({443, 8443})
MAX_REDIRECTS = 3
MAX_URL_LENGTH = 2000
MAX_PROPFIND_BYTES = 16 * 1024**2
MAX_ERROR_BYTES = 64 * 1024
MAX_XML_DEPTH = 32
MAX_XML_ELEMENTS = 400_000
MAX_RESPONSES = 20_000
MAX_TEXT = 4096
PROPFIND_DEADLINE = 120.0
CONNECT_CHECK_DEADLINE = 30.0
# Gesamtdauer eines Downloads: Grundzeit + Mindestrate (langsame Server brechen nicht sofort ab,
# hängende Verbindungen aber nach endlicher Zeit)
DOWNLOAD_BASE_SECONDS = 60.0
DOWNLOAD_MIN_RATE = 256 * 1024

_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
_TLD = re.compile(r"^(?:[a-z][a-z0-9-]*|xn--[a-z0-9-]+)$")
_BLOCKED_SUFFIXES = (
    ".localhost", ".local", ".internal", ".home.arpa", ".arpa", ".lan", ".intranet", ".corp", ".private",
    ".localdomain", ".home",
)
_BLOCKED_NAMES = frozenset({"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback", "metadata.google.internal"})
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_URL_SAFE = "/%:@!$&'()*+,;=-._~"

PROPFIND_BODY = (
    b'<?xml version="1.0" encoding="utf-8"?>'
    b'<d:propfind xmlns:d="DAV:"><d:prop>'
    b"<d:resourcetype/><d:getcontentlength/><d:getlastmodified/><d:getcontenttype/><d:getetag/>"
    b"</d:prop></d:propfind>"
)


# --- Adresse prüfen --------------------------------------------------------------------------


@dataclass(frozen=True)
class Origin:
    scheme: str
    host: str
    port: int

    @property
    def netloc(self) -> str:
        default = 443 if self.scheme == "https" else 80
        return self.host if self.port == default else f"{self.host}:{self.port}"

    def url(self, target: str) -> str:
        return f"{self.scheme}://{self.netloc}{target}"


def check_host_name(host: str) -> str:
    """Normalisierter Hostname oder HostNotAllowed. Keine IP-Literale, keine internen Namen."""
    host = (host or "").strip().lower().rstrip(".")
    if not host or len(host) > 253:
        raise HostNotAllowed("host")
    try:
        ipaddress.ip_address(host.strip("[]").split("%", 1)[0])
    except ValueError:
        pass
    else:
        raise HostNotAllowed("ip_literal")
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise HostNotAllowed("host") from exc
    labels = host.split(".")
    if len(labels) < 2 or not all(_LABEL.match(label) for label in labels) or not _TLD.match(labels[-1]):
        # Auch «127.1», «0x7f.0.0.1», «2130706433»: die letzte Label muss ein Name sein
        raise HostNotAllowed("host")
    if host in _BLOCKED_NAMES or any(host.endswith(suffix) for suffix in _BLOCKED_SUFFIXES):
        raise HostNotAllowed("internal_name")
    return host


def check_origin(scheme: str, host: str, port: int | None, *, allow_http: bool) -> Origin:
    scheme = (scheme or "").lower()
    if scheme != "https" and not (allow_http and scheme == "http"):
        raise HostNotAllowed("scheme")
    host = check_host_name(host)
    port = port if port is not None else (443 if scheme == "https" else 80)
    if scheme == "https" and port not in ALLOWED_PORTS:
        raise HostNotAllowed("port")
    if scheme == "http" and port not in (80, 8080):
        raise HostNotAllowed("port")
    return Origin(scheme, host, port)


def _clean_segments(path: str) -> list[str]:
    """Dekodierte Pfadsegmente; ``..``, ``.``, Steuerzeichen und Backslash sind nie erlaubt."""
    segments = []
    for raw in path.split("/"):
        if raw == "":
            continue
        try:
            segment = unquote(raw, errors="strict")
        except UnicodeDecodeError as exc:
            raise HostNotAllowed("path") from exc
        if segment in (".", "..") or "/" in segment or "\\" in segment or _CONTROL.search(segment) or len(segment) > 255:
            raise HostNotAllowed("path")
        segments.append(segment)
    return segments


def parse_base_url(url: str, *, allow_http: bool = False) -> tuple[Origin, str]:
    """Basisadresse → (Ursprung, dekodierter Basispfad mit «/» am Ende)."""
    url = (url or "").strip()
    if not url or len(url) > MAX_URL_LENGTH or _CONTROL.search(url) or " " in url:
        raise HostNotAllowed("invalid_url")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise HostNotAllowed("invalid_url") from exc
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise HostNotAllowed("userinfo")
    if parts.query or parts.fragment or url.endswith(("?", "#")):
        raise HostNotAllowed("invalid_url")
    origin = check_origin(parts.scheme, parts.hostname or "", port, allow_http=allow_http)
    segments = _clean_segments(parts.path)
    base_path = "/" + "".join(f"{segment}/" for segment in segments)
    return origin, base_path


def canonical_url(origin: Origin, base_path: str) -> str:
    return origin.url(quote(base_path, safe="/"))


def resolve_checked(host: str, port: int) -> str:
    """DNS-Auflösung; eine einzige nicht-öffentliche Adresse genügt zur Ablehnung."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError) as exc:
        raise ProviderError("network", detail="dns") from exc
    addresses = [info[4][0] for info in infos]
    if not addresses:
        raise ProviderError("network", detail="dns")
    for address in addresses:
        try:
            public = ip_is_public(address)
        except ValueError:
            public = False
        if not public:
            raise HostNotAllowed("private_address")
    return addresses[0]


# --- Transport -------------------------------------------------------------------------------


class DavTransport(Protocol):
    def open(
        self, method: str, origin: Origin, target: str, headers: dict[str, str], body: bytes | None, *, deadline: float | None = None,
    ) -> RawResponse: ...


class _PinnedConnection(http.client.HTTPSConnection):
    """Verbindet mit der vorab geprüften Adresse, prüft das Zertifikat aber auf den Hostnamen."""

    def __init__(self, host: str, port: int, address: str, context: ssl.SSLContext) -> None:
        super().__init__(host, port, timeout=CONNECT_TIMEOUT, context=context)
        self._address = address
        self._ssl_context = context

    _raw: socket.socket | None = None

    def connect(self) -> None:
        sock = socket.create_connection((self._address, self.port), CONNECT_TIMEOUT)
        self._raw = sock
        try:
            sock.settimeout(READ_TIMEOUT)
            self.sock = self._ssl_context.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


    def abort(self) -> None:
        """Vom Watchdog: Verbindung hart beenden (auch mitten im TLS-Handshake oder Header-Empfang)."""
        for sock in (self._raw, self.sock):
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass


class _Watchdog:
    """Gesamtzeit je Anfrage: die Lese-Inaktivität (60 s je recv) allein begrenzt einen Server nicht,
    der Handshake oder Header Byte für Byte liefert. Nach Ablauf wird der Socket geschlossen."""

    def __init__(self, connection, seconds: float | None) -> None:
        self._timer: threading.Timer | None = None
        abort = getattr(connection, "abort", None)
        if seconds is not None and abort is not None:
            self._timer = threading.Timer(max(0.1, seconds), abort)
            self._timer.daemon = True
            self._timer.start()

    def cancel(self) -> None:
        if self._timer is not None:
            self._timer.cancel()


class _Response:
    def __init__(self, connection: http.client.HTTPSConnection, response: http.client.HTTPResponse, watchdog: _Watchdog | None = None) -> None:
        self._connection = connection
        self._watchdog = watchdog
        self._response = response
        self.status = response.status
        self.headers = {key.lower(): value for key, value in response.getheaders()}

    def read(self, amount: int) -> bytes:
        return self._response.read(amount)

    def close(self) -> None:
        if self._watchdog is not None:
            self._watchdog.cancel()
        try:
            self._response.close()
        finally:
            self._connection.close()


class RealDavTransport:
    """Echte Verbindungen: nur https, Port aus ALLOWED_PORTS, geprüfte und gepinnte Adresse."""

    def __init__(self) -> None:
        self._context = ssl.create_default_context()

    def open(
        self, method: str, origin: Origin, target: str, headers: dict[str, str], body: bytes | None, *, deadline: float | None = None,
    ) -> RawResponse:
        # Zweite Prüfung an der einzigen Stelle, die wirklich verbindet (auch für Redirect-Ziele)
        checked = check_origin(origin.scheme, origin.host, origin.port, allow_http=False)
        remaining = None if deadline is None else deadline - time.monotonic()
        if remaining is not None and remaining <= 0:
            raise ProviderError("network", detail="timeout")
        address = resolve_checked(checked.host, checked.port)
        connection = _PinnedConnection(checked.host, checked.port, address, self._context)
        watchdog = _Watchdog(connection, remaining)
        try:
            connection.request(method, target, body=body, headers=headers)
            response = connection.getresponse()
        except (OSError, http.client.HTTPException, ValueError) as exc:
            # ValueError: z. B. UnicodeEncodeError bei Nicht-ASCII im Ziel - nie ein unkuratierter 500
            watchdog.cancel()
            connection.close()
            raise ProviderError("network", detail=type(exc).__name__) from exc
        return _Response(connection, response, watchdog)


class FakeDavTransport:
    """Nachgebauter Server (Tests, E2E mit CLOUD_IMPORT_FAKE_PROVIDERS): kein Netz, kein DNS.
    ``host`` im FakeRequest ist ``origin.netloc``; alle übrigen Regeln laufen unverändert."""

    def __init__(self, fake: FakeTransport) -> None:
        self.fake = fake

    def open(
        self, method: str, origin: Origin, target: str, headers: dict[str, str], body: bytes | None, *, deadline: float | None = None,
    ) -> RawResponse:
        return self.fake.open(method, origin.netloc, target, headers, body)


# --- Zugangsdaten ----------------------------------------------------------------------------


@dataclass(frozen=True)
class DavCredentials:
    """Basisadresse, Benutzer, App-Passwort. Gespeichert nur verschlüsselt (token_crypto) als JSON
    in ``import_connection.access_token_encrypted``; nie in Logs (``repr`` ohne Passwort)."""

    base_url: str
    username: str
    password: str = field(repr=False)

    def __repr__(self) -> str:
        return f"DavCredentials(base_url={self.base_url!r}, username=***)"

    def to_json(self) -> str:
        return json.dumps({"v": 1, "url": self.base_url, "user": self.username, "password": self.password})

    @classmethod
    def from_json(cls, raw: str | None) -> DavCredentials:
        try:
            data = json.loads(raw or "")
        except ValueError as exc:
            raise ProviderUnauthorized(detail="credentials") from exc
        if not isinstance(data, dict) or not all(isinstance(data.get(key), str) for key in ("url", "user", "password")):
            raise ProviderUnauthorized(detail="credentials")
        return cls(base_url=data["url"], username=data["user"], password=data["password"])


def validate_username(value: str) -> str:
    value = (value or "").strip()
    if not value or len(value) > 200 or ":" in value or _CONTROL.search(value):
        raise ValueError("username")
    return value


def validate_password(value: str) -> str:
    if not value or len(value) > 500 or _CONTROL.search(value):
        raise ValueError("password")
    return value


# --- Antworten -------------------------------------------------------------------------------


@dataclass
class DavEntry:
    path: str  # dekodiert, relativ zur Basis, ohne führenden/abschliessenden «/» ("" = Basis selbst)
    is_collection: bool
    size: int | None = None
    modified_at: datetime | None = None
    content_type: str | None = None
    etag: str | None = None


class XmlRejected(ProviderError):
    def __init__(self, reason: str) -> None:
        super().__init__("bad_response", detail=f"xml_{reason}")


_DAV = "DAV:"


def parse_multistatus(body: bytes) -> list[dict]:
    """PROPFIND-Antwort (207) sicher lesen: ohne DTD/Entitäten, mit Tiefen- und Mengengrenzen.
    Ergebnis je <response>: {"href", "props" (nur aus propstat 200), "status"}."""
    if len(body) > MAX_PROPFIND_BYTES:
        raise XmlRejected("too_large")
    parser = expat.ParserCreate(namespace_separator=" ")
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)

    def reject(*_args):
        raise XmlRejected("dtd")

    parser.StartDoctypeDeclHandler = reject
    parser.EntityDeclHandler = reject
    parser.UnparsedEntityDeclHandler = reject
    parser.NotationDeclHandler = reject
    parser.ExternalEntityRefHandler = reject
    parser.SkippedEntityHandler = reject

    responses: list[dict] = []
    stack: list[str] = []
    counter = {"elements": 0}
    current: dict | None = None
    propstat: dict | None = None
    text: list[str] = []

    def start(name: str, _attrs) -> None:
        nonlocal current, propstat
        counter["elements"] += 1
        if counter["elements"] > MAX_XML_ELEMENTS:
            raise XmlRejected("too_many_elements")
        stack.append(name)
        if len(stack) > MAX_XML_DEPTH:
            raise XmlRejected("too_deep")
        text.clear()
        if name == f"{_DAV} response":
            if len(responses) >= MAX_RESPONSES:
                raise XmlRejected("too_many_responses")
            current = {"href": None, "props": {}, "status": None}
        elif name == f"{_DAV} propstat" and current is not None:
            propstat = {"props": {}, "status": None}
        elif name == f"{_DAV} collection" and propstat is not None and len(stack) >= 2 and stack[-2] == f"{_DAV} resourcetype":
            propstat["props"]["collection"] = True

    def end(name: str) -> None:
        nonlocal current, propstat
        value = "".join(text).strip()[:MAX_TEXT]
        text.clear()
        stack.pop()
        parent = stack[-1] if stack else ""
        if current is None:
            return
        if name == f"{_DAV} href" and parent == f"{_DAV} response":
            current["href"] = value
        elif name == f"{_DAV} status":
            if parent == f"{_DAV} propstat" and propstat is not None:
                propstat["status"] = value
            elif parent == f"{_DAV} response":
                current["status"] = value
        elif propstat is not None and parent == f"{_DAV} prop":
            local = name.split(" ", 1)[1] if name.startswith(f"{_DAV} ") else None
            if local in ("getcontentlength", "getlastmodified", "getcontenttype", "getetag"):
                propstat["props"][local] = value
        elif name == f"{_DAV} propstat" and propstat is not None:
            if _status_ok(propstat["status"]):
                current["props"].update(propstat["props"])
            propstat = None
        elif name == f"{_DAV} response":
            responses.append(current)
            current = None

    def chars(data: str) -> None:
        if sum(len(part) for part in text) < MAX_TEXT:
            text.append(data)

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = chars
    try:
        parser.Parse(body, True)
    except expat.ExpatError as exc:
        raise XmlRejected("syntax") from exc
    return responses


def _status_ok(status: str | None) -> bool:
    if not status:
        return True
    parts = status.split()
    return len(parts) >= 2 and parts[1].startswith("2")


def _parse_int(value: str | None) -> int | None:
    if value and value.isdigit() and len(value) <= 18:
        return int(value)
    return None


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    return when if when.tzinfo else when.replace(tzinfo=UTC)


def normalize_rel(path: str) -> str:
    """Relativer Pfad (dekodiert) ohne «/» am Rand; ``..``/Steuerzeichen → ValueError."""
    segments = []
    for segment in path.split("/"):
        if segment == "":
            continue
        if segment in (".", "..") or "\\" in segment or _CONTROL.search(segment) or len(segment) > 255:
            raise ValueError("path")
        segments.append(segment)
    return "/".join(segments)


# --- Client ----------------------------------------------------------------------------------


@dataclass
class DavClient:
    credentials: DavCredentials
    transport: DavTransport
    allow_http: bool = False
    origin: Origin = field(init=False)
    base_path: str = field(init=False)

    def __post_init__(self) -> None:
        self.origin, self.base_path = parse_base_url(self.credentials.base_url, allow_http=self.allow_http)

    def __repr__(self) -> str:
        return f"DavClient(origin={self.origin.netloc!r})"

    def _auth(self) -> str:
        raw = f"{self.credentials.username}:{self.credentials.password}".encode()
        return "Basic " + base64.b64encode(raw).decode("ascii")

    def target_for(self, rel: str) -> str:
        return quote(self.base_path + normalize_rel(rel), safe="/")

    def _headers(self, origin: Origin, extra: dict[str, str]) -> dict[str, str]:
        headers = {"User-Agent": user_agent(), **extra}
        headers.pop("Authorization", None)
        if origin == self.origin:
            # Zugangsdaten nur an den Ursprung, den der Verein eingegeben hat
            headers["Authorization"] = self._auth()
        return headers

    def _open(
        self, method: str, origin: Origin, target: str, headers: dict[str, str], body: bytes | None, *, deadline: float | None = None,
    ) -> RawResponse:
        sent = self._headers(origin, headers)
        if body is not None:
            sent["Content-Length"] = str(len(body))
        raw = self.transport.open(method, origin, target, sent, body, deadline=deadline)
        _logger.debug("cloud-import webdav %s %s%s → %s", method, origin.netloc, target.split("?", 1)[0], raw.status)
        return raw

    def _redirect(self, current: Origin, location: str | None, base_target: str, *, same_origin: bool) -> tuple[Origin, str]:
        if not location or len(location) > MAX_URL_LENGTH or _CONTROL.search(location):
            raise ProviderError("bad_response", detail="redirect")
        absolute = urljoin(current.url(base_target), location)
        try:
            parts = urlsplit(absolute)
            port = parts.port
        except ValueError as exc:
            raise HostNotAllowed("invalid_url") from exc
        if parts.username is not None or parts.password is not None:
            raise HostNotAllowed("userinfo")
        origin = check_origin(parts.scheme, parts.hostname or "", port, allow_http=self.allow_http)
        if same_origin and origin != self.origin:
            raise HostNotAllowed("redirect_origin")
        # Nicht-ASCII (latin-1-dekodierte Header) prozentkodieren, vorhandene %-Folgen bleiben
        target = quote(parts.path or "/", safe=_URL_SAFE)
        if parts.query:
            target = f"{target}?{quote(parts.query, safe=_URL_SAFE)}"
        return origin, target

    @staticmethod
    def _read_all(raw: RawResponse, limit: int, deadline: float) -> bytes:
        data = bytearray()
        while True:
            if time.monotonic() > deadline:
                raise ProviderError("network", detail="timeout")
            try:
                chunk = raw.read(CHUNK)
            except (OSError, http.client.HTTPException) as exc:
                raise ProviderError("network", detail=type(exc).__name__) from exc
            if not chunk:
                return bytes(data)
            data += chunk
            if len(data) > limit:
                raise ProviderError("bad_response", status=raw.status, detail="too_large")

    @staticmethod
    def _raise_for_status(status: int, headers: dict[str, str]) -> None:
        if status in (429, 503):
            raise ProviderThrottled(parse_retry_after(headers.get("retry-after")), status=status)
        if status == 401:
            raise ProviderUnauthorized()
        if status == 403:
            raise ProviderError("access_denied", status=status)
        if status == 404:
            raise ProviderError("not_found", status=status)
        if status >= 500:
            raise ProviderError("server_error", status=status)
        raise ProviderError("bad_request", status=status)

    def propfind(self, rel: str, *, depth: int, deadline_seconds: float = PROPFIND_DEADLINE) -> list[DavEntry]:
        """PROPFIND mit Depth 0 oder 1 (nie «infinity»). Ergebnis ohne fremde/ungültige Einträge."""
        if depth not in (0, 1):
            raise ValueError("depth")
        rel = normalize_rel(rel)
        deadline = time.monotonic() + deadline_seconds
        origin, target = self.origin, self.target_for(rel)
        if rel:
            target += "/"
        hops = 0
        while True:
            raw = self._open(
                "PROPFIND", origin, target,
                {"Depth": str(depth), "Content-Type": "application/xml; charset=utf-8", "Accept": "application/xml, text/xml"},
                PROPFIND_BODY, deadline=deadline,
            )
            try:
                if raw.status in (301, 302, 303, 307, 308):
                    hops += 1
                    if hops > MAX_REDIRECTS:
                        raise ProviderError("bad_response", status=raw.status, detail="too_many_redirects")
                    origin, target = self._redirect(origin, raw.headers.get("location"), target, same_origin=True)
                    continue
                if raw.status != 207:
                    if raw.status < 400:
                        raise ProviderError("bad_response", status=raw.status, detail="not_multistatus")
                    self._raise_for_status(raw.status, raw.headers)
                declared = raw.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > MAX_PROPFIND_BYTES:
                    raise ProviderError("bad_response", status=raw.status, detail="too_large")
                body = self._read_all(raw, MAX_PROPFIND_BYTES, deadline)
            finally:
                raw.close()
            return self._entries(parse_multistatus(body), origin, rel, depth)

    def _entries(self, responses: list[dict], origin: Origin, rel: str, depth: int) -> list[DavEntry]:
        entries: list[DavEntry] = []
        base = self.base_path
        for response in responses:
            href = response.get("href")
            if not href or not _status_ok(response.get("status")):
                continue
            try:
                parts = urlsplit(href)
            except ValueError:
                continue
            if parts.netloc and (parts.scheme.lower(), parts.netloc.lower()) != (origin.scheme, origin.netloc.lower()):
                continue  # fremder Host im href: nie übernehmen
            try:
                path = "/" + "/".join(_clean_segments(parts.path))
            except HostNotAllowed:
                continue
            if not (path + "/").startswith(base):
                continue
            try:
                entry_rel = normalize_rel(path[len(base) - 1 :])
            except ValueError:
                continue
            if entry_rel == rel:
                if depth == 0:
                    entries.append(self._entry(entry_rel, response["props"]))
                continue
            parent = entry_rel.rsplit("/", 1)[0] if "/" in entry_rel else ""
            if depth == 1 and parent == rel:
                entries.append(self._entry(entry_rel, response["props"]))
        return entries

    @staticmethod
    def _entry(rel: str, props: dict) -> DavEntry:
        content_type = (props.get("getcontenttype") or "").split(";", 1)[0].strip()[:200] or None
        return DavEntry(
            path=rel, is_collection=bool(props.get("collection")), size=_parse_int(props.get("getcontentlength")),
            modified_at=_parse_date(props.get("getlastmodified")), content_type=content_type,
            etag=(props.get("getetag") or "").strip('"')[:200] or None,
        )

    def download(self, rel: str, dest: Path, max_bytes: int) -> DownloadResult:
        """GET als Stream nach ``dest`` (nie in den Speicher), Grenze am Strom gemessen, SHA-256 nebenbei.
        Redirects: jedes Ziel geprüft; Zugangsdaten nur an den Ursprung."""
        rel = normalize_rel(rel)
        if not rel:
            raise ProviderError("not_found")
        deadline = time.monotonic() + DOWNLOAD_BASE_SECONDS + max_bytes / DOWNLOAD_MIN_RATE
        origin, target = self.origin, self.target_for(rel)
        hops = 0
        while True:
            raw = self._open("GET", origin, target, {"Accept": "*/*"}, None, deadline=deadline)
            try:
                if raw.status in (301, 302, 303, 307, 308):
                    hops += 1
                    if hops > MAX_REDIRECTS:
                        raise ProviderError("bad_response", status=raw.status, detail="too_many_redirects")
                    origin, target = self._redirect(origin, raw.headers.get("location"), target, same_origin=False)
                    continue
                if raw.status != 200:
                    if raw.status < 400:
                        raise ProviderError("bad_response", status=raw.status, detail="status")
                    if raw.status == 401 and origin != self.origin:
                        # Fremdes Redirect-Ziel (ohne Zugangsdaten) lehnt ab: das Passwort ist nicht
                        # das Problem - kein needs_reauth, kein Löschen der Zugangsdaten
                        raise ProviderError("access_denied", status=401, detail="redirect_target")
                    self._raise_for_status(raw.status, raw.headers)
                declared = raw.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > max_bytes:
                    raise DownloadTooLarge()
                return _stream(raw, dest, max_bytes, deadline)
            finally:
                raw.close()


def _stream(raw: RawResponse, dest: Path, max_bytes: int, deadline: float) -> DownloadResult:
    digest = hashlib.sha256()
    size = 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with dest.open("wb") as handle:
            while True:
                if time.monotonic() > deadline:
                    raise ProviderError("network", detail="timeout")
                try:
                    chunk = raw.read(CHUNK)
                except (OSError, http.client.HTTPException) as exc:
                    raise ProviderError("network", detail=type(exc).__name__) from exc
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise DownloadTooLarge()
                digest.update(chunk)
                handle.write(chunk)
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    return DownloadResult(size=size, sha256=digest.hexdigest(), content_type=raw.headers.get("content-type"))


# --- Referenzen ------------------------------------------------------------------------------

ROOT_REF = "p"
_REF = re.compile(r"^p[A-Za-z0-9_-]{0,599}$")


def encode_ref(rel: str) -> str:
    """Pfad → undurchsichtige Referenz für den Browser (base64url, passt zu base.SAFE_REF)."""
    rel = normalize_rel(rel)
    return ROOT_REF + base64.urlsafe_b64encode(rel.encode("utf-8")).decode("ascii").rstrip("=")


def decode_ref(ref: str) -> str:
    if not _REF.match(ref or ""):
        raise ValueError("ref")
    data = ref[1:]
    try:
        rel = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("ref") from exc
    if normalize_rel(rel) != rel or unicodedata.category(rel[:1] or "a") == "Cc":
        raise ValueError("ref")
    return rel


__all__ = [
    "ALLOWED_PORTS", "DavClient", "DavCredentials", "DavEntry", "FakeDavTransport", "HttpResponse", "Origin",
    "RealDavTransport", "XmlRejected", "check_host_name", "check_origin", "decode_ref", "encode_ref",
    "parse_base_url", "parse_multistatus", "resolve_checked",
]
