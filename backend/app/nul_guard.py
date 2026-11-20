"""NUL-Zeichen (U+0000) in Anfragen früh als Eingabefehler ablehnen.

PostgreSQL kann NUL weder in Textfeldern noch in JSONB speichern oder vergleichen. Ohne diese
Prüfung scheiterte eine Anfrage mit NUL erst in der Datenbank (psycopg.DataError): je nach Route
als 500 oder als 400 mit Eintrag im Fehlerprotokoll, obwohl nur die Eingabe ungültig war
(Nachtlauf 2026-11-20, Termine; dasselbe Muster in vielen weiteren Routen). Statt jede Route
einzeln abzusichern, prüft diese Middleware zentral:

- Pfad und Query-String (``%00``),
- JSON-Bodies (``\\u0000``, nicht aber ein escapter Backslash vor «u0000» als normaler Text).

Multipart-Uploads (Dateien dürfen NUL-Bytes enthalten) und andere Inhaltstypen bleiben
unberührt; Formularfelder in Multipart prüfen die Routen selbst. Die Grösse eines JSON-Bodys
begrenzt RequestBodyLimitMiddleware (weiter aussen), bevor er hier gepuffert wird.
"""
from __future__ import annotations

import re

from starlette.responses import JSONResponse

_BODY_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
# \u0000 mit einer geraden Zahl (auch 0) Backslashes davor: ein echtes JSON-Escape. Bei ungerader
# Zahl ist der erste Backslash escapt und «u0000» nur Text.
_JSON_NUL_ESCAPE = re.compile(rb"(?<!\\)(?:\\\\)*\\u0000")
_DETAIL = [{"type": "string_nul", "loc": ["request"], "msg": "must not contain NUL characters"}]


def contains_json_nul(body: bytes) -> bool:
    return b"\x00" in body or _JSON_NUL_ESCAPE.search(body) is not None


def _url_contains_nul(scope) -> bool:
    raw_path = scope.get("raw_path") or scope.get("path", "").encode("utf-8", "surrogateescape")
    query = scope.get("query_string") or b""
    return b"%00" in raw_path or b"\x00" in raw_path or b"%00" in query or b"\x00" in query


class NulGuardMiddleware:
    def __init__(self, app, *, prefix: str = "/api/"):
        self.app = app
        self.prefix = prefix

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope.get("path", "").startswith(self.prefix):
            return await self.app(scope, receive, send)
        if _url_contains_nul(scope):
            return await JSONResponse({"detail": _DETAIL}, 422)(scope, receive, send)
        if scope.get("method") not in _BODY_METHODS:
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        if not headers.get(b"content-type", b"").lower().startswith(b"application/json"):
            return await self.app(scope, receive, send)

        # JSON-Body puffern (Starlette liest ihn ohnehin ganz) und danach unverändert weiterreichen.
        chunks: list[bytes] = []
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunks.append(message.get("body", b""))
            if not message.get("more_body", False):
                break
        body = b"".join(chunks)
        if contains_json_nul(body):
            return await JSONResponse({"detail": _DETAIL}, 422)(scope, receive, send)

        replayed = False

        async def replay():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)
