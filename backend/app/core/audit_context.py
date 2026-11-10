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


def current_client_ip() -> str | None:
    return _client_ip.get()


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

        token = _client_ip.set(client_ip(HTTPConnection(scope)))
        try:
            await self.app(scope, receive, send)
        finally:
            _client_ip.reset(token)
