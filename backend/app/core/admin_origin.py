"""WebAuthn-Origin und -Host der Admin-Passkeys (Registrierung, Login, Step-up).

Mit konfigurierter Admin-Domain ist der erwartete Origin fest ``https://<Admin-Domain>`` (Security-
Audit SEC-021: ein Vergleich mit dem Origin-Header desselben Requests prüft nichts). Über OpenZiti
wird die Admin-Domain auf Port 443 angesprochen; nur wenn sie direkt mit dem konfigurierten
Host-Port des Admin-Entrypoints (TRAEFIK_ADMIN_PORT) aufgerufen wird, gilt dieser Origin. Nur lokal ohne Admin-Domain (Entwicklung,
E2E-Stack) gelten Origin und Host der Anfrage - dort laufen die Requests über Next.js' /api-Rewrite,
dessen Host-Header der Backend-Container ist, deshalb der Origin-Header des Browsers.
"""
from __future__ import annotations

from urllib.parse import urlparse

from starlette.requests import Request

from app.core.config import settings


def _browser_origin(request: Request) -> str:
    origin = request.headers.get("origin")
    if origin:
        return origin
    host = request.headers.get("host") or request.url.netloc
    if host.startswith("localhost") or host.startswith("127.0.0.1"):
        return f"http://{host}"
    return f"https://{host}"


def expected_admin_origin(request: Request) -> str:
    if settings.traefik_admin_domain:
        base = f"https://{settings.traefik_admin_domain.strip().lower().rstrip('.')}"
        # Aufruf direkt über den Host-Port des Admin-Entrypoints (z. B. per SSH-Tunnel oder
        # Abnahme-Skript): nur genau dieser konfigurierte Port, nie ein beliebiger aus dem Request.
        port = settings.traefik_admin_port
        if port and port != 443 and (request.headers.get("origin") or "").lower() == f"{base}:{port}":
            return f"{base}:{port}"
        return base
    return _browser_origin(request)


def admin_request_hostname(request: Request) -> str | None:
    return urlparse(_browser_origin(request)).hostname
