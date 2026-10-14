"""Serverseitige Durchsetzung des Wartungsmodus (siehe app/services/maintenance_service.py).

Reine ASGI-Middleware, damit auch WebSockets erfasst werden (Starlettes BaseHTTPMiddleware sieht
nur den http-Scope). Gesperrte HTTP-Anfragen bekommen 503 mit Retry-After und einem
maschinenlesbaren Code, den das Frontend in die Wartungsansicht übersetzt; WebSockets werden mit
1013 ("try again later") geschlossen.

Immer erlaubt: Healthchecks, der öffentliche Wartungsstatus, die Plattform-Admin-API
(Notfallfunktionen und Wartungsverwaltung - eigener, OpenZiti-geschützter Zugang), der
Status-Endpunkt für Uptime Kuma, Logout und die Mandantenauflösung der Anmeldeseite.
"""

from __future__ import annotations

import json

from starlette.types import ASGIApp, Receive, Scope, Send

from app.services.maintenance_service import EffectiveState, current_effective_state

EXEMPT_PREFIXES = (
    "/api/admin/",
    "/api/health",
    "/api/public/maintenance-status",
    "/api/system-status/summary",
)
EXEMPT_EXACT = ("/api/auth/logout", "/api/auth/tenant-by-domain")
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")
UPLOAD_PATH_MARKERS = ("upload", "/images", "/word-import", "/import", "/profile-image", "/parts")


def is_exempt(path: str) -> bool:
    return path in EXEMPT_EXACT or any(path == prefix.rstrip("/") or path.startswith(prefix) for prefix in EXEMPT_PREFIXES)


def blocked_reason(state: EffectiveState, *, method: str, path: str, content_type: str) -> str | None:
    """None = durchlassen, sonst der Grund ("maintenance" / "maintenance_writes" / "maintenance_uploads")."""
    if not path.startswith("/api") or is_exempt(path) or method == "OPTIONS":
        return None
    if state.full_active:
        return "maintenance"
    if method in SAFE_METHODS:
        return None
    if state.writes_blocked:
        return "maintenance_writes"
    if state.uploads_blocked and (content_type.startswith("multipart/") or any(marker in path for marker in UPLOAD_PATH_MARKERS)):
        return "maintenance_uploads"
    return None


class MaintenanceMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if not path.startswith("/api") or is_exempt(path):
            await self.app(scope, receive, send)
            return
        state = current_effective_state()
        if not state.any_blocking:
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            if state.full_active or state.writes_blocked:
                await send({"type": "websocket.close", "code": 1013, "reason": "maintenance"})
                return
            await self.app(scope, receive, send)
            return
        headers = {key.decode("latin-1").lower(): value.decode("latin-1") for key, value in scope.get("headers", [])}
        reason = blocked_reason(state, method=scope.get("method", "GET"), path=path, content_type=headers.get("content-type", ""))
        if reason is None:
            await self.app(scope, receive, send)
            return
        body = json.dumps({
            "detail": "hocX wird gerade gewartet. Bitte später erneut versuchen.",
            "code": reason,
            "estimated_end_at": state.estimated_end_at.isoformat() if state.estimated_end_at else None,
        }).encode()
        await send({
            "type": "http.response.start",
            "status": 503,
            "headers": [
                (b"content-type", b"application/json"),
                (b"retry-after", str(state.retry_after_seconds()).encode()),
                (b"cache-control", b"no-store"),
                (b"x-hocx-maintenance", reason.encode()),
                (b"content-length", str(len(body)).encode()),
            ],
        })
        await send({"type": "http.response.body", "body": body})
