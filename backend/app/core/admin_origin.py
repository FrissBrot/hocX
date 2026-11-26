"""WebAuthn-Origin und -Host der Admin-Passkeys (Registrierung, Login, Step-up).

Mit konfigurierter Admin-Domain ist der erwartete Origin fest ``https://<Admin-Domain>`` (Security-
Audit SEC-021: ein Vergleich mit dem Origin-Header desselben Requests prüft nichts). Über OpenZiti
wird die Admin-Domain auf Port 443 angesprochen (der Browser meldet keinen Port); ein Aufruf über
einen anderen Port wird für Passkeys bewusst nicht unterstützt. Nur lokal ohne Admin-Domain (Entwicklung,
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
    """Nie aus Client-Headern, sobald eine Admin-Domain konfiguriert ist (ausserhalb der Entwicklung
    erzwingt admin_gate.validate_startup das, Review L3)."""
    if settings.traefik_admin_domain:
        return f"https://{settings.traefik_admin_domain.strip().lower().rstrip('.')}"
    return _browser_origin(request)


def admin_request_hostname(request: Request) -> str | None:
    # Nicht lesbarer Origin (z. B. «http://[»): unbekannter Host statt 500 (Nachtlauf 2026-11-26)
    try:
        return urlparse(_browser_origin(request)).hostname
    except ValueError:
        return None
