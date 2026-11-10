"""Vorprüfung für Multipart-Requests, bevor Starlette den Body auf die Platte spoolt.

Audit MAIN-SEC-004: FastAPI parst Form-/File-Bodies vor den Auth-Dependencies. Starlette
schreibt Datei-Parts über 1 MB in temporäre Dateien, ohne Gesamtlimit - ein anonymer
Angreifer konnte so beliebig viele GB in /tmp des Containers schieben, bevor das 401 kam.

Diese Middleware greift nur für ``multipart/*`` unter ``/api/`` (ausser den Pfaden mit
eigener Admission-Middleware, z. B. Galerie-Uploads):

- ohne gültig signiertes Session-Cookie (Benutzer bzw. unter ``/api/admin/`` Plattform-Admin)
  sofort 401, ohne den Body zu lesen - die Signaturprüfung braucht keine DB; die eigentliche
  Berechtigung prüft weiterhin die Route;
- Grösse pro Pfadpräfix begrenzt (Content-Length vorab, gezählte Bytes während des Lesens).
"""
from __future__ import annotations

from http.cookies import CookieError, SimpleCookie

from starlette.formparsers import MultiPartException
from starlette.responses import JSONResponse

from app.core.admin_security import parse_admin_session_token
from app.core.config import settings
from app.core.security import parse_session_token

_MUTATING_METHODS = {"POST", "PUT", "PATCH"}


class MultipartGuardMiddleware:
    def __init__(
        self,
        app,
        *,
        default_max_bytes: int,
        path_limits: tuple[tuple[str, int], ...] = (),
        skip_prefixes: tuple[str, ...] = (),
    ):
        self.app = app
        self.default_max_bytes = default_max_bytes
        # Längstes Präfix zuerst, damit spezifischere Grenzen gewinnen.
        self.path_limits = tuple(sorted(path_limits, key=lambda item: len(item[0]), reverse=True))
        self.skip_prefixes = skip_prefixes

    def _limit_for(self, path: str) -> int:
        for prefix, max_bytes in self.path_limits:
            if path.startswith(prefix):
                return max_bytes
        return self.default_max_bytes

    @staticmethod
    def _cookies(headers: dict[bytes, bytes]) -> dict[str, str]:
        raw = headers.get(b"cookie", b"").decode("latin-1")
        if not raw:
            return {}
        parsed = SimpleCookie()
        try:
            parsed.load(raw)
        except CookieError:
            return {}
        return {key: morsel.value for key, morsel in parsed.items()}

    def _is_authenticated(self, path: str, headers: dict[bytes, bytes]) -> bool:
        cookies = self._cookies(headers)
        if path.startswith("/api/admin/"):
            return parse_admin_session_token(cookies.get(settings.admin_session_cookie)) is not None
        return parse_session_token(cookies.get(settings.auth_session_cookie)) is not None

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") not in _MUTATING_METHODS:
            return await self.app(scope, receive, send)
        path: str = scope["path"]
        if not path.startswith("/api/") or path.startswith(self.skip_prefixes):
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        if not headers.get(b"content-type", b"").lower().startswith(b"multipart/"):
            return await self.app(scope, receive, send)

        if not self._is_authenticated(path, headers):
            return await JSONResponse({"detail": "Not authenticated"}, 401)(scope, receive, send)

        max_bytes = self._limit_for(path)
        try:
            length = int(headers.get(b"content-length", b"0"))
            if length < 0:
                raise ValueError
        except ValueError:
            return await JSONResponse({"detail": "Ungültige Uploadgrösse"}, 400)(scope, receive, send)
        if length > max_bytes:
            return await JSONResponse({"detail": "Upload insgesamt zu gross"}, 413)(scope, receive, send)

        received = 0
        too_large = False

        async def bounded_receive():
            nonlocal received, too_large
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > max_bytes:
                    too_large = True
                    raise MultiPartException("Upload insgesamt zu gross")
            return message

        async def bounded_send(message):
            if message["type"] == "http.response.start" and too_large:
                message = {**message, "status": 413}
            await send(message)

        await self.app(scope, bounded_receive, bounded_send)
