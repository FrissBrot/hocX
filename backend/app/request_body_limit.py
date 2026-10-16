"""Grössenlimit für Request-Bodies ausser Multipart (MAIN-OPS-013).

Starlette liest JSON- und andere Bodies vollständig in den Speicher; bisher ohne Obergrenze.
Multipart-Uploads begrenzt MultipartGuardMiddleware (bzw. UploadAdmissionMiddleware für die
Galerie) pro Pfad; diese Middleware deckt den Rest unter ``/api/`` ab. Das Limit ist bewusst
nicht in Traefik gesetzt: dessen Buffering-Middleware puffert auch Antworten und bricht damit
WebSockets und gestreamte Downloads.
"""
from __future__ import annotations

from starlette.responses import JSONResponse

_BODY_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class _BodyTooLarge(Exception):
    pass


class RequestBodyLimitMiddleware:
    def __init__(self, app, *, max_bytes: int, skip_prefixes: tuple[str, ...] = ()):
        self.app = app
        self.max_bytes = max_bytes
        self.skip_prefixes = skip_prefixes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") not in _BODY_METHODS:
            return await self.app(scope, receive, send)
        path: str = scope["path"]
        if not path.startswith("/api/") or path.startswith(self.skip_prefixes):
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        if headers.get(b"content-type", b"").lower().startswith(b"multipart/"):
            return await self.app(scope, receive, send)
        try:
            length = int(headers.get(b"content-length", b"0"))
        except ValueError:
            length = 0
        if length > self.max_bytes:
            return await JSONResponse({"detail": "Anfrage zu gross"}, 413)(scope, receive, send)

        received = 0
        response_started = False

        async def bounded_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise _BodyTooLarge
            return message

        async def tracking_send(message):
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, bounded_receive, tracking_send)
        except _BodyTooLarge:
            # Ohne Content-Length (chunked) erst beim Lesen bemerkt.
            if not response_started:
                await JSONResponse({"detail": "Anfrage zu gross"}, 413)(scope, receive, send)
