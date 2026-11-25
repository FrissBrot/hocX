"""Ausgehendes HTTP der Cloud-Quellen (Plan §10.1, E-9: Host-Allowlist im Code, kein Egress-Proxy).

Regeln, die hier und nur hier durchgesetzt werden:

- Nur ``https`` auf Port 443, nur Hosts aus der ``HostPolicy`` des Anbieters (fest im Code).
- Vor jedem Verbindungsaufbau DNS-Auflösung; liegt *eine* Adresse nicht im öffentlichen Internet
  (privat, Loopback, Link-Local, Multicast, reserviert …), wird nicht verbunden. Verbunden wird mit
  genau der geprüften Adresse (kein zweites Auflösen → kein DNS-Rebinding), TLS mit SNI und
  Zertifikatsprüfung auf den Hostnamen.
- Redirects folgt der Client nie automatisch. ``download`` folgt höchstens MAX_REDIRECTS selbst und
  prüft jedes Ziel erneut gegen die Allowlist.
- Das Bearer-Token geht nur an die API-Hosts des Anbieters (``api_hosts``) - an Download-Hosts nur,
  wenn der Anbieter es für diese Hosts ausdrücklich verlangt (``bearer_download_suffixes``, z. B.
  SharePoint nach dem Ende der tempauth-URLs am 1.4.2027).
- 429/503 → ``ProviderThrottled`` mit ``Retry-After`` (Anbieter verlangen, nicht früher zu wiederholen).
- Logs enthalten nur Methode, Host, Pfad ohne Query und Status - nie Header, Query (tempauth!) oder
  Antworten. Ausnahmetexte enthalten ebenfalls keine URLs mit Query.

Tests und der E2E-Stack ersetzen nur den ``Transport`` (``fake_http.FakeTransport``); alle Regeln
oben laufen unverändert mit.
"""

from __future__ import annotations

import email.utils
import hashlib
import http.client
import ipaddress
import json
import logging
import os
import socket
import ssl
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from urllib.parse import urlencode, urljoin, urlsplit

_logger = logging.getLogger(__name__)

CONNECT_TIMEOUT = 10.0
READ_TIMEOUT = 60.0
MAX_REDIRECTS = 3
# Obergrenze je Download (auch bei tröpfelnden Servern; READ_TIMEOUT gilt nur je Lesevorgang)
DOWNLOAD_DEADLINE = 30 * 60
MAX_JSON_BYTES = 8 * 1024**2
CHUNK = 256 * 1024
RETRY_AFTER_DEFAULT = 30
RETRY_AFTER_MAX = 3600


# --- Fehler (kuratierte Codes, ohne URL/Token im Text) ---------------------------------------


class ProviderError(Exception):
    """Fehler beim Anbieter. ``code`` ist kuratiert und wird übersetzt bzw. im Bericht gezeigt."""

    def __init__(self, code: str, *, status: int | None = None, detail: str | None = None) -> None:
        super().__init__(code if detail is None else f"{code}: {detail}")
        self.code = code
        self.status = status
        # Fehlercode des Anbieters (z. B. "invalid_grant", "itemNotFound"), nie Freitext mit Daten
        self.detail = detail


class HostNotAllowed(ProviderError):
    def __init__(self, reason: str) -> None:
        super().__init__("host_not_allowed", detail=reason)


class ProviderThrottled(ProviderError):
    def __init__(self, retry_after: int, *, status: int) -> None:
        super().__init__("throttled", status=status)
        self.retry_after = retry_after


class ProviderUnauthorized(ProviderError):
    def __init__(self, *, detail: str | None = None) -> None:
        super().__init__("unauthorized", status=401, detail=detail)


class DownloadTooLarge(ProviderError):
    def __init__(self) -> None:
        super().__init__("too_large")


# --- Allowlist -------------------------------------------------------------------------------


@dataclass(frozen=True)
class HostPolicy:
    """Erlaubte Ziele eines Anbieters. ``api_hosts`` exakt (Bearer erlaubt), Download-Hosts über
    Suffixe (``.sharepoint.com`` trifft ``verein.sharepoint.com``, nicht ``evilsharepoint.com``)."""

    api_hosts: frozenset[str]
    download_suffixes: tuple[str, ...] = ()
    bearer_download_suffixes: tuple[str, ...] = ()
    # Exakte Hosts ohne Bearer-Token (z. B. Token-Endpunkt des Identitätsanbieters)
    plain_hosts: frozenset[str] = frozenset()

    @staticmethod
    def _match(host: str, suffixes: tuple[str, ...]) -> bool:
        return any(suffix.startswith(".") and host.endswith(suffix) and len(host) > len(suffix) for suffix in suffixes)

    def allowed(self, host: str) -> bool:
        return host in self.api_hosts or host in self.plain_hosts or self._match(host, self.download_suffixes)

    def bearer_always(self, host: str) -> bool:
        return host in self.api_hosts

    def bearer_on_request(self, host: str) -> bool:
        return self._match(host, self.bearer_download_suffixes)


def check_url(url: str, policy: HostPolicy) -> tuple[str, str]:
    """(host, Pfad+Query) oder HostNotAllowed. Nur https, Port 443, keine Zugangsdaten in der URL."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise HostNotAllowed("invalid_url") from exc
    host = (parts.hostname or "").lower().rstrip(".")
    if parts.scheme != "https":
        raise HostNotAllowed("scheme")
    if port not in (None, 443):
        raise HostNotAllowed("port")
    if parts.username or parts.password:
        raise HostNotAllowed("userinfo")
    if not host or not policy.allowed(host):
        raise HostNotAllowed("host")
    target = parts.path or "/"
    if parts.query:
        target = f"{target}?{parts.query}"
    return host, target


def _log_target(host: str, target: str) -> str:
    return f"{host}{target.split('?', 1)[0]}"


# --- Transport -------------------------------------------------------------------------------


class RawResponse(Protocol):
    status: int
    headers: dict[str, str]

    def read(self, amount: int) -> bytes: ...

    def close(self) -> None: ...


class Transport(Protocol):
    def open(self, method: str, host: str, target: str, headers: dict[str, str], body: bytes | None) -> RawResponse: ...


def _ip_is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast and not ip.is_reserved


def resolve_public(host: str) -> str:
    """Löst den Host auf; eine einzige nicht-öffentliche Adresse genügt zur Ablehnung."""
    try:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ProviderError("network", detail="dns") from exc
    addresses = [info[4][0] for info in infos]
    if not addresses:
        raise ProviderError("network", detail="dns")
    for address in addresses:
        try:
            public = _ip_is_public(address)
        except ValueError:
            public = False
        if not public:
            raise HostNotAllowed("private_address")
    return addresses[0]


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Verbindet mit der vorab geprüften Adresse, prüft das Zertifikat aber auf den Hostnamen."""

    def __init__(self, host: str, address: str, context: ssl.SSLContext) -> None:
        super().__init__(host, 443, timeout=CONNECT_TIMEOUT, context=context)
        self._address = address
        self._ssl_context = context

    def connect(self) -> None:
        sock = socket.create_connection((self._address, 443), CONNECT_TIMEOUT)
        sock.settimeout(READ_TIMEOUT)
        self.sock = self._ssl_context.wrap_socket(sock, server_hostname=self.host)


class _HttpClientResponse:
    def __init__(self, connection: http.client.HTTPSConnection, response: http.client.HTTPResponse) -> None:
        self._connection = connection
        self._response = response
        self.status = response.status
        self.headers = {key.lower(): value for key, value in response.getheaders()}

    def read(self, amount: int) -> bytes:
        return self._response.read(amount)

    def close(self) -> None:
        try:
            self._response.close()
        finally:
            self._connection.close()


class RealTransport:
    def __init__(self) -> None:
        self._context = ssl.create_default_context()

    def open(self, method: str, host: str, target: str, headers: dict[str, str], body: bytes | None) -> RawResponse:
        address = resolve_public(host)
        connection = _PinnedHTTPSConnection(host, address, self._context)
        try:
            connection.request(method, target, body=body, headers=headers)
            response = connection.getresponse()
        except (OSError, http.client.HTTPException) as exc:
            connection.close()
            raise ProviderError("network", detail=type(exc).__name__) from exc
        return _HttpClientResponse(connection, response)


# --- Client ----------------------------------------------------------------------------------


def user_agent() -> str:
    # Microsoft-Empfehlung [M12]: «ISV|Firma|App/Version» - Drosselung wird dann der App zugeordnet.
    return f"ISV|hocX|hocX/{os.environ.get('HOCX_VERSION') or 'dev'}"


@dataclass
class HttpResponse:
    status: int
    headers: dict[str, str]
    body: bytes = b""

    def json(self) -> dict:
        try:
            data = json.loads(self.body.decode("utf-8") or "{}")
        except (UnicodeDecodeError, ValueError) as exc:
            raise ProviderError("bad_response", status=self.status, detail="json") from exc
        if not isinstance(data, dict):
            raise ProviderError("bad_response", status=self.status, detail="json")
        return data


@dataclass
class DownloadResult:
    size: int
    sha256: str
    content_type: str | None = None


def parse_retry_after(value: str | None, *, now: float | None = None) -> int:
    if not value:
        return RETRY_AFTER_DEFAULT
    value = value.strip()
    if value.isdigit():
        seconds = int(value)
    else:
        try:
            when = email.utils.parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return RETRY_AFTER_DEFAULT
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        seconds = int(when.timestamp() - (now if now is not None else time.time()))
    return max(1, min(RETRY_AFTER_MAX, seconds))


def _provider_error_code(body: bytes) -> str | None:
    """Fehlercode des Anbieters aus der Antwort (OAuth: error, Graph: error.code) - nur der Code."""
    try:
        data = json.loads(body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    error = data.get("error")
    if isinstance(error, dict):
        error = error.get("code")
    if isinstance(error, str) and len(error) <= 80 and all(ch.isalnum() or ch in "_.-" for ch in error):
        return error
    return None


def raise_for_status(response: HttpResponse) -> None:
    status = response.status
    if status < 400:
        return
    if status in (429, 503):
        raise ProviderThrottled(parse_retry_after(response.headers.get("retry-after")), status=status)
    detail = _provider_error_code(response.body)
    if status == 401:
        raise ProviderUnauthorized(detail=detail)
    if status == 403:
        raise ProviderError("access_denied", status=status, detail=detail)
    if status == 404:
        raise ProviderError("not_found", status=status, detail=detail)
    if status >= 500:
        raise ProviderError("server_error", status=status, detail=detail)
    raise ProviderError("bad_request", status=status, detail=detail)


@dataclass
class SafeHttpClient:
    policy: HostPolicy
    transport: Transport = field(default_factory=RealTransport)

    def _headers(self, host: str, bearer: str | None, extra: dict[str, str] | None, *, send_bearer: bool) -> dict[str, str]:
        headers = {"User-Agent": user_agent(), "Accept": "application/json", **(extra or {})}
        headers.pop("Authorization", None)  # nur hier gesetzt, nie vom Aufrufer
        if bearer and send_bearer:
            headers["Authorization"] = f"Bearer {bearer}"
        return headers

    def _open(self, method: str, url: str, *, bearer: str | None, send_bearer: bool, headers: dict[str, str] | None, body: bytes | None):
        host, target = check_url(url, self.policy)
        sent = self._headers(host, bearer, headers, send_bearer=send_bearer)
        if body is not None:
            sent["Content-Length"] = str(len(body))
        raw = self.transport.open(method, host, target, sent, body)
        _logger.debug("cloud-import %s %s → %s", method, _log_target(host, target), raw.status)
        return raw

    def request(
        self, method: str, url: str, *, bearer: str | None = None, headers: dict[str, str] | None = None,
        form: dict[str, str] | None = None, max_bytes: int = MAX_JSON_BYTES,
    ) -> HttpResponse:
        """Einzelner Request ohne Redirect-Folgen. Bearer nur an API-Hosts."""
        body = None
        extra = dict(headers or {})
        if form is not None:
            body = urlencode(form).encode("ascii")
            extra["Content-Type"] = "application/x-www-form-urlencoded"
        host, _target = check_url(url, self.policy)
        raw = self._open(method, url, bearer=bearer, send_bearer=self.policy.bearer_always(host), headers=extra, body=body)
        try:
            data = bytearray()
            while True:
                chunk = raw.read(CHUNK)
                if not chunk:
                    break
                data += chunk
                if len(data) > max_bytes:
                    raise ProviderError("bad_response", status=raw.status, detail="too_large")
            return HttpResponse(raw.status, dict(raw.headers), bytes(data))
        except (OSError, http.client.HTTPException) as exc:
            raise ProviderError("network", detail=type(exc).__name__) from exc
        finally:
            raw.close()

    def get_json(self, url: str, *, bearer: str | None = None, headers: dict[str, str] | None = None) -> dict:
        response = self.request("GET", url, bearer=bearer, headers=headers)
        if 300 <= response.status < 400:
            raise ProviderError("bad_response", status=response.status, detail="redirect")
        raise_for_status(response)
        return response.json()

    def post_form(self, url: str, form: dict[str, str]) -> HttpResponse:
        return self.request("POST", url, form=form)

    def download(self, url: str, *, bearer: str | None, dest: Path, max_bytes: int, bearer_mode: str = "never") -> DownloadResult:
        """Streamt nach ``dest`` (nie in den Speicher), höchstens ``max_bytes`` (gemessen am Strom),
        und berechnet SHA-256 nebenbei. Redirects selbst, je Hop Allowlist-Prüfung.

        bearer_mode für Download-Hosts aus ``bearer_download_suffixes``: "never", "on_401" (zuerst
        ohne, bei 401 einmal mit Token) oder "always". An API-Hosts geht das Token immer."""
        current = url
        retried_with_bearer = False
        hops = 0
        while True:
            host, _target = check_url(current, self.policy)
            send = self.policy.bearer_always(host) or (
                self.policy.bearer_on_request(host) and (bearer_mode == "always" or retried_with_bearer)
            )
            raw = self._open("GET", current, bearer=bearer, send_bearer=send, headers={"Accept": "*/*"}, body=None)
            try:
                if 300 <= raw.status < 400 and raw.status != 304:
                    location = raw.headers.get("location")
                    if not location:
                        raise ProviderError("bad_response", status=raw.status, detail="redirect")
                    hops += 1
                    if hops > MAX_REDIRECTS:
                        raise ProviderError("bad_response", status=raw.status, detail="too_many_redirects")
                    current = urljoin(current, location)
                    retried_with_bearer = False
                    continue
                if (
                    raw.status == 401 and bearer and not send and not retried_with_bearer
                    and bearer_mode == "on_401" and self.policy.bearer_on_request(host)
                ):
                    retried_with_bearer = True
                    continue
                if raw.status == 401 and not self.policy.bearer_always(host):
                    # 401 vom Download-Host ist kein abgelaufenes API-Token (kein Refresh, kein
                    # needs_reauth), sondern eine abgelehnte Download-URL
                    raise ProviderError("access_denied", status=401, detail="download")
                if raw.status >= 400:
                    body = raw.read(64 * 1024)
                    raise_for_status(HttpResponse(raw.status, dict(raw.headers), body))
                declared = raw.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > max_bytes:
                    raise DownloadTooLarge()
                return self._stream(raw, dest, max_bytes)
            finally:
                raw.close()

    @staticmethod
    def _stream(raw: RawResponse, dest: Path, max_bytes: int) -> DownloadResult:
        digest = hashlib.sha256()
        size = 0
        deadline = time.monotonic() + DOWNLOAD_DEADLINE
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            with dest.open("wb") as handle:
                while True:
                    try:
                        chunk = raw.read(CHUNK)
                    except (OSError, http.client.HTTPException) as exc:
                        raise ProviderError("network", detail=type(exc).__name__) from exc
                    if not chunk:
                        break
                    if time.monotonic() > deadline:
                        raise ProviderError("network", detail="deadline")
                    size += len(chunk)
                    if size > max_bytes:
                        raise DownloadTooLarge()
                    digest.update(chunk)
                    handle.write(chunk)
        except BaseException:
            dest.unlink(missing_ok=True)
            raise
        return DownloadResult(size=size, sha256=digest.hexdigest(), content_type=raw.headers.get("content-type"))


def utcnow() -> datetime:
    return datetime.now(UTC)
