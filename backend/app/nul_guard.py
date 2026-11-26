"""NUL-Zeichen (U+0000) in Anfragen früh als Eingabefehler ablehnen.

PostgreSQL kann NUL weder in Textfeldern noch in JSONB speichern oder vergleichen. Ohne diese
Prüfung scheiterte eine Anfrage mit NUL erst in der Datenbank (psycopg.DataError): je nach Route
als 500 oder als 400 mit Eintrag im Fehlerprotokoll, obwohl nur die Eingabe ungültig war
(Nachtlauf 2026-11-20, Termine; dasselbe Muster in vielen weiteren Routen). Statt jede Route
einzeln abzusichern, prüft diese Middleware zentral:

- Pfad und Query-String (``%00``),
- JSON-Bodies (``\\u0000``, nicht aber ein escapter Backslash vor «u0000» als normaler Text),
- einzelne UTF-16-Surrogate in JSON-Bodies (``"\\ud800"`` ohne Partner): Python macht daraus einen
  str, der sich nicht als UTF-8 kodieren lässt - jede Route scheiterte damit erst beim Hashen,
  in Redis oder in der Datenbank mit 500 (Nachtlauf 2026-11-26, Login ohne Anmeldung).

Multipart-Uploads (Dateien dürfen NUL-Bytes enthalten) und andere Inhaltstypen bleiben
unberührt; Formularfelder in Multipart prüfen die Routen selbst. Die Grösse eines JSON-Bodys
begrenzt RequestBodyLimitMiddleware (weiter aussen), bevor er hier gepuffert wird.
"""
from __future__ import annotations

import json
import re

from starlette.responses import JSONResponse

_BODY_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
# \u0000 mit einer geraden Zahl (auch 0) Backslashes davor: ein echtes JSON-Escape. Bei ungerader
# Zahl ist der erste Backslash escapt und «u0000» nur Text.
_JSON_NUL_ESCAPE = re.compile(rb"(?<!\\)(?:\\\\)*\\u0000")
# Escape eines Surrogats (U+D800-U+DFFF), ebenfalls nur mit gerader Zahl Backslashes davor
_JSON_SURROGATE_ESCAPE = re.compile(rb"(?<!\\)(?:\\\\)*\\u[dD][89a-fA-F][0-9a-fA-F]{2}")
_DETAIL = [{"type": "string_nul", "loc": ["request"], "msg": "must not contain NUL characters"}]
_SURROGATE_DETAIL = [{"type": "string_unicode", "loc": ["request"], "msg": "must not contain unpaired surrogates"}]


def contains_json_nul(body: bytes) -> bool:
    return b"\x00" in body or _JSON_NUL_ESCAPE.search(body) is not None


def contains_json_lone_surrogate(body: bytes) -> bool:
    """Gültige Paare (Emoji als ``\\ud83d\\ude00``) ergeben beim Parsen ein normales Zeichen; nur ein
    Surrogat ohne Partner bleibt übrig und lässt sich nicht als UTF-8 kodieren. Geparst wird nur,
    wenn überhaupt ein Surrogat-Escape vorkommt; ungültiges JSON lehnt FastAPI selbst ab."""
    if _JSON_SURROGATE_ESCAPE.search(body) is None:
        return False
    try:
        parsed = json.loads(body)
    except (ValueError, RecursionError):
        return False
    try:
        json.dumps(parsed, ensure_ascii=False).encode("utf-8")
    except UnicodeEncodeError:
        return True
    return False


def parsed_as_json(content_type: bytes | None) -> bool:
    """Wie FastAPI (``fastapi.routing``, ``strict_content_type`` = Standard): ``application/json`` und
    ``application/*+json`` werden als JSON gelesen, ein Body ohne Content-Type nicht. Nur
    ``application/json`` zu prüfen liess NUL und Surrogate über ``application/vnd.api+json`` an der
    Prüfung vorbei (Nachtlauf 2026-11-26)."""
    if not content_type:
        return False
    media_type = content_type.split(b";", 1)[0].strip().lower()
    if not media_type.startswith(b"application/"):
        return False
    subtype = media_type[len(b"application/"):]
    return subtype == b"json" or subtype.endswith(b"+json")


def _replay_then(body: bytes, receive, *, more_body: bool):
    """Erst den gepufferten Teil liefern, danach wieder vom Client lesen."""
    replayed = False

    async def replay():
        nonlocal replayed
        if not replayed:
            replayed = True
            return {"type": "http.request", "body": body, "more_body": more_body}
        return await receive()

    return replay


def _url_contains_nul(scope) -> bool:
    raw_path = scope.get("raw_path") or scope.get("path", "").encode("utf-8", "surrogateescape")
    query = scope.get("query_string") or b""
    return b"%00" in raw_path or b"\x00" in raw_path or b"%00" in query or b"\x00" in query


class NulGuardMiddleware:
    def __init__(self, app, *, prefix: str = "/api/", max_buffer_bytes: int = 16 * 1024 * 1024):
        self.app = app
        self.prefix = prefix
        # Höchstens so viel puffern: unter den Galerie-/Import-Pfaden begrenzt RequestBodyLimit nicht,
        # ein grosser Body ohne Content-Type läge sonst ganz im Speicher. Darüber ungeprüft weiter
        # (die Route lehnt einen solchen Body ohnehin ab, JSON-Bodies sind sonst kleiner).
        self.max_buffer_bytes = max_buffer_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope.get("path", "").startswith(self.prefix):
            return await self.app(scope, receive, send)
        if _url_contains_nul(scope):
            return await JSONResponse({"detail": _DETAIL}, 422)(scope, receive, send)
        if scope.get("method") not in _BODY_METHODS:
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        if not parsed_as_json(headers.get(b"content-type")):
            return await self.app(scope, receive, send)

        # JSON-Body puffern (Starlette liest ihn ohnehin ganz) und danach unverändert weiterreichen.
        chunks: list[bytes] = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunks.append(message.get("body", b""))
            size += len(chunks[-1])
            if not message.get("more_body", False):
                break
            if size > self.max_buffer_bytes:
                return await self.app(scope, _replay_then(b"".join(chunks), receive, more_body=True), send)
        body = b"".join(chunks)
        if contains_json_nul(body):
            return await JSONResponse({"detail": _DETAIL}, 422)(scope, receive, send)
        if contains_json_lone_surrogate(body):
            return await JSONResponse({"detail": _SURROGATE_DETAIL}, 422)(scope, receive, send)

        await self.app(scope, _replay_then(body, receive, more_body=False), send)
