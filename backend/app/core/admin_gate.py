"""Plattform-Admin-API nur über den Admin-Einstieg (Auth-Audit SEC-AUTH-001, Defense in Depth).

Das Admin-Panel ist nur über die Admin-Domain auf Traefiks Entrypoint `adminsecure` erreichbar
(an 127.0.0.1 gebunden, davor der OpenZiti-Tunnel). Bisher war das ausschliesslich eine
Routing-Eigenschaft von Traefik - ein Router ohne `!PathPrefix(/api/admin)` (z. B. die Router der
Mandanten-Domains) machte die ganze Admin-API aus dem Internet erreichbar. Diese Middleware prüft
deshalb im Backend selbst, dass ein Request unter `/api/admin` wirklich über den Admin-Einstieg kam:

1. **Gate-Header:** Jeder Admin-Router in Traefik setzt `X-Hocx-Admin-Gate` auf ein Secret
   (`ADMIN_GATE_SECRET`, Middleware `admin-gate@file`, von `scripts/deploy.sh` als Datei in
   `infra/traefik/dynamic/admin-gate.yml` geschrieben). Auf den öffentlichen Entrypoints entfernt
   Traefik den Header (`admin-gate-strip@file`), er lässt sich von aussen also nicht mitschicken.
2. **Host:** Ist `TRAEFIK_ADMIN_DOMAIN` gesetzt, muss der Request auf diese Domain lauten (`Host`,
   oder bei Aufrufen des Next.js-Servers über `INTERNAL_API_URL` `X-Forwarded-Host` von einem
   vertrauenswürdigen Proxy, siehe `client_ip.py`).

Der Next.js-Server ruft die Admin-API serverseitig direkt auf (`http://backend:8000`, nicht über
Traefik) und reicht dafür Gate-Header und Host weiter, die er selbst von Traefik bekommen hat
(`frontend/lib/admin-gate.ts`). Das Secret selbst kennt das Frontend nicht.

Ohne Secret:
- Entwicklung (`HOCX_ENVIRONMENT` development/dev/local, auch der E2E-Stack): kein Gate, die
  Admin-API ist wie bisher erreichbar (dort gibt es keinen OpenZiti-Einstieg).
- Alle anderen Umgebungen (production, test): fail closed - die Admin-API antwortet überall mit
  404, und beim Start landet ein Eintrag im Fehlerprotokoll.

Abgelehnt wird immer mit derselben 404 wie für einen unbekannten Pfad (kein Hinweis darauf, dass
es die Admin-API gibt). Gilt für HTTP und WebSocket.
"""

from __future__ import annotations

import hmac
import logging

from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.client_ip import _is_trusted
from app.core.config import settings

logger = logging.getLogger(__name__)

ADMIN_API_PREFIX = "/api/admin"
GATE_HEADER = "x-hocx-admin-gate"
DEVELOPMENT_ENVIRONMENT_NAMES = frozenset({"development", "dev", "local"})

MODE_ENFORCE = "enforce"
MODE_OPEN = "open"
MODE_CLOSED = "closed"


def is_admin_api_path(path: str) -> bool:
    return path == ADMIN_API_PREFIX or path.startswith(ADMIN_API_PREFIX + "/")


def gate_mode() -> str:
    """enforce: Secret gesetzt. open: Entwicklung ohne Secret. closed: sonst (fail closed)."""
    if settings.admin_gate_secret:
        return MODE_ENFORCE
    if settings.environment.strip().lower() in DEVELOPMENT_ENVIRONMENT_NAMES:
        return MODE_OPEN
    return MODE_CLOSED


def _hostname(value: str | None) -> str:
    """Host ohne Port, klein geschrieben. IPv6-Literale ([::1]:8443) bleiben in Klammern."""
    value = (value or "").strip().lower()
    if value.startswith("["):
        return value.split("]", 1)[0] + "]"
    return value.rsplit(":", 1)[0] if ":" in value else value


def _host_allowed(headers: dict[str, str], peer: str | None) -> bool:
    admin_domain = (settings.traefik_admin_domain or "").strip().lower().rstrip(".")
    if not admin_domain:
        return True
    if _hostname(headers.get("host")) == admin_domain:
        return True
    # Serverseitige Aufrufe des Next.js-Servers (INTERNAL_API_URL) tragen Host "backend:8000" und
    # die ursprüngliche Domain in X-Forwarded-Host - nur von einem vertrauenswürdigen Proxy.
    forwarded = headers.get("x-forwarded-host")
    if forwarded and peer and _is_trusted(peer):
        return _hostname(forwarded.split(",")[0]) == admin_domain
    return False


def admin_request_allowed(headers: dict[str, str], peer: str | None) -> bool:
    mode = gate_mode()
    if mode == MODE_OPEN:
        return True
    if mode == MODE_CLOSED:
        return False
    provided = headers.get(GATE_HEADER, "")
    if not provided or not hmac.compare_digest(provided.encode("utf-8"), (settings.admin_gate_secret or "").encode("utf-8")):
        return False
    return _host_allowed(headers, peer)


def is_development() -> bool:
    return settings.environment.strip().lower() in DEVELOPMENT_ENVIRONMENT_NAMES


def validate_startup() -> None:
    """Review L3: Ausserhalb der Entwicklung startet die API nur mit Admin-Domain und Gate-Secret
    (mindestens 32 Zeichen) - sonst hinge die Isolation an einer fehlenden Variable. Der Deploy
    scheitert dann an den Smoke-Checks und rollt zurück."""
    if is_development():
        return
    problems = []
    if not (settings.traefik_admin_domain or "").strip():
        problems.append("TRAEFIK_ADMIN_DOMAIN fehlt")
    if len(settings.admin_gate_secret or "") < 32:
        problems.append("ADMIN_GATE_SECRET fehlt oder ist kürzer als 32 Zeichen")
    if problems:
        raise RuntimeError("Admin-Isolation nicht konfiguriert: " + ", ".join(problems))


def log_gate_configuration() -> None:
    """Beim Start: fehlendes Secret ausserhalb der Entwicklung ins Fehlerprotokoll (Admin-Panel und
    ntfy sehen es sonst nie - das Panel selbst ist dann ja nicht erreichbar)."""
    mode = gate_mode()
    if mode == MODE_OPEN:
        logger.warning("ADMIN_GATE_SECRET nicht gesetzt: Admin-API ohne Gate (nur Entwicklung).")
        return
    if mode != MODE_CLOSED:
        return
    logger.error("ADMIN_GATE_SECRET fehlt: die Admin-API ist gesperrt (fail closed).")
    from app.core.db import SessionLocal
    from app.core.error_log import record_system_error

    with SessionLocal() as db:
        record_system_error(
            db,
            exc=RuntimeError(
                "ADMIN_GATE_SECRET fehlt: die Plattform-Admin-API ist gesperrt. "
                "scripts/deploy.sh erzeugt das Secret und die Traefik-Datei admin-gate.yml (RUNBOOK, Admin-Zugang)."
            ),
        )


_NOT_FOUND_BODY = b'{"detail":"Not Found"}'


class AdminGateMiddleware:
    """Äusserste Schicht: lehnt `/api/admin/*` ab, bevor irgendetwas anderes (Rate-Limits,
    Wartung, Datenbank) läuft."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket") or not is_admin_api_path(scope.get("path", "")):
            await self.app(scope, receive, send)
            return
        headers = {key.decode("latin-1").lower(): value.decode("latin-1") for key, value in scope.get("headers", [])}
        client = scope.get("client")
        if admin_request_allowed(headers, client[0] if client else None):
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            # Vor dem Accept geschlossen: uvicorn antwortet auf den Handshake mit 403.
            await send({"type": "websocket.close", "code": 1008})
            return
        await send(
            {
                "type": "http.response.start",
                "status": 404,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(_NOT_FOUND_BODY)).encode())],
            }
        )
        await send({"type": "http.response.body", "body": _NOT_FOUND_BODY})
