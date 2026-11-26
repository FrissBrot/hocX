"""CSRF-Schutz über den Origin-Header (Security-Audit release/1.2.0, SEC-009).

Bisher schützte allein `SameSite=Lax` das Session-Cookie. Eine Seite derselben Site (etwa eine
Geschwister-Subdomain der Hauptdomain) hätte damit Formular-POSTs mit Cookie auslösen können.
Diese Middleware lehnt zustandsändernde Requests ab, deren `Origin` weder zum eigenen Host noch
zur CORS-Allowlist gehört.

- Ohne `Origin`-Header (Server-zu-Server, CLI, ältere Clients) bleibt alles wie bisher: Browser
  senden bei Cross-Site-Requests immer einen Origin, also entsteht hier keine Lücke.
- „Eigener Host“ ist `Host` oder `X-Forwarded-Host` (Next.js-Rewrite im Dev/E2E-Stack). Eine
  fremde Seite kann `X-Forwarded-Host` nicht ohne CORS-Preflight setzen, und den beantwortet die
  CORS-Allowlist.
- Custom-Domains der Mandanten sind über den Host abgedeckt (Traefik leitet ihn unverändert weiter).
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from starlette.types import ASGIApp, Receive, Scope, Send

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _origin_netloc(origin: str) -> str | None:
    if not origin or origin == "null":
        return None
    try:
        parts = urlsplit(origin)
    except ValueError:
        # z. B. «http://[» (Invalid IPv6 URL): kein Browser sendet das, also fremde Herkunft
        return None
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return None
    return parts.netloc.lower()


def origin_hostname(origin: str) -> str | None:
    """Hostname aus einem Origin-Header; ValueError bei nicht lesbarem Wert (z. B. «http://[»)."""
    return urlsplit(origin).hostname


def origin_allowed(origin: str, *, host: str | None, forwarded_host: str | None, allowed_origins: set[str]) -> bool:
    if origin in allowed_origins:
        return True
    netloc = _origin_netloc(origin)
    if netloc is None:
        return False
    own_hosts = {h.strip().lower() for h in (host, *(forwarded_host or "").split(",")) if h and h.strip()}
    return netloc in own_hosts


class OriginGuardMiddleware:
    def __init__(self, app: ASGIApp, *, allowed_origins: set[str], exempt_path_pattern: str | None = None) -> None:
        self.app = app
        self.allowed_origins = set(allowed_origins)
        # Einzelne Pfade ohne Sitzung, die bewusst cross-site gePOSTet werden (OAuth form_post).
        # Nur ein vollständig verankertes Muster; die Route schützt sich selbst (state, PKCE).
        self.exempt_path = re.compile(exempt_path_pattern) if exempt_path_pattern else None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method", "GET").upper() not in UNSAFE_METHODS:
            await self.app(scope, receive, send)
            return
        if self.exempt_path is not None and self.exempt_path.fullmatch(scope.get("path", "")):
            await self.app(scope, receive, send)
            return
        headers = {key.decode("latin-1").lower(): value.decode("latin-1") for key, value in scope.get("headers", [])}
        origin = headers.get("origin")
        if origin is None or origin_allowed(
            origin, host=headers.get("host"), forwarded_host=headers.get("x-forwarded-host"), allowed_origins=self.allowed_origins
        ):
            await self.app(scope, receive, send)
            return
        body = b'{"detail":"Anfrage von fremder Herkunft abgelehnt."}'
        await send({
            "type": "http.response.start",
            "status": 403,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
        })
        await send({"type": "http.response.body", "body": body})
