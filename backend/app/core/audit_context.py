"""Quelladresse eines Requests für das Audit-Log (Datenschutz-Audit PRIV-013).

Die Middleware legt die Client-IP (app/core/client_ip.py) in eine ContextVar, ``AuditService.log``
liest sie von dort - so bekommt jeder Eintrag aus einem Request seinen IP-Fingerprint, ohne dass
jeder Aufrufer die Adresse durchreichen muss. Gespeichert wird nie die Adresse selbst, sondern ein
HMAC des gekürzten Netzes (IPv4 /24, IPv6 /48): genug, um Zugriffe einer Quelle zusammenzufassen,
zu wenig, um eine Person über die Adresse zu identifizieren.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
from contextvars import ContextVar

from app.core.client_ip import client_ip

_client_ip: ContextVar[str | None] = ContextVar("audit_client_ip", default=None)
# Korrelation (Auth-Audit 2026-11-20, Abschnitt 10.1): Request-ID, User-Agent und Host des Requests
_request_meta: ContextVar[dict[str, str | None] | None] = ContextVar("audit_request_meta", default=None)


def current_client_ip() -> str | None:
    return _client_ip.get()


def current_request_meta() -> dict[str, str | None]:
    """``request_id``, ``user_agent``, ``host``, ``path`` des laufenden Requests (leer ausserhalb)."""
    return _request_meta.get() or {}


def ip_fingerprint(address: str | None) -> str | None:
    from app.core.config import settings

    if not address:
        return None
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return None
    network = ipaddress.ip_network(f"{ip}/{24 if ip.version == 4 else 48}", strict=False)
    # Eigener Ableitungszweck, damit der Wert nie einem anderen HMAC mit AUTH_SECRET entspricht.
    key = hmac.new(settings.auth_secret.encode(), b"hocx audit ip fingerprint v1", hashlib.sha256).digest()
    return hmac.new(key, str(network).encode(), hashlib.sha256).hexdigest()[:16]


class AuditContextMiddleware:
    """Reine ASGI-Middleware (kein BaseHTTPMiddleware): die ContextVar gilt für den ganzen Request,
    auch in synchronen Routen, die Starlette im Threadpool mit kopiertem Kontext ausführt."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        from starlette.requests import HTTPConnection

        import uuid

        connection = HTTPConnection(scope)
        request_id = uuid.uuid4().hex
        token = _client_ip.set(client_ip(connection))
        meta_token = _request_meta.set({
            "request_id": request_id,
            "user_agent": (connection.headers.get("user-agent") or "")[:512] or None,
            "host": (connection.url.hostname or "")[:255] or None,
            "path": scope.get("path"),
        })

        async def send_with_request_id(message):
            if message["type"] == "http.response.start":
                message.setdefault("headers", [])
                message["headers"] = [*message["headers"], (b"x-request-id", request_id.encode())]
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id if scope["type"] == "http" else send)
        finally:
            _request_meta.reset(meta_token)
            _client_ip.reset(token)
