"""Einzelne UTF-16-Surrogate in Auth-Eingaben (Nachtlauf 2026-11-26, auth-session/eingaben).

JSON erlaubt ``"\\ud800"``; Python macht daraus einen str, der sich nicht als UTF-8 kodieren lässt.
Erwartet: Eingabefehler (4xx) statt 500 mit Eintrag im Fehlerprotokoll."""
from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.core import rate_limit
from app.core.db import get_db
from app.core.redis_client import get_redis_sync
from app.main import app

SURROGATE = "\\ud800"


def _flush() -> None:
    client = get_redis_sync()
    for pattern in ("ratelimit:*", "authsec:*", "authblock:*"):
        for key in client.scan_iter(pattern):
            client.delete(key)
    rate_limit.local_window.clear()


@pytest.fixture(autouse=True)
def _clean():
    _flush()
    yield
    _flush()


@pytest.mark.parametrize(("path", "body"), [
    ("/api/auth/login", '{"email": "a@example.com", "password": "x%sy"}' % SURROGATE),
    ("/api/auth/login", '{"email": "a%s@example.com", "password": "secret"}' % SURROGATE),
    ("/api/auth/password-reset/request", '{"email": "a%s@example.com"}' % SURROGATE),
    ("/api/auth/account-link/complete", '{"token": "t%s", "password": "aaaaaaaaaaaaaaaa"}' % SURROGATE),
    ("/api/auth/bridge/preview", '{"token": "t%s"}' % SURROGATE),
])
def test_lone_surrogate_is_an_input_error(db, path, body):
    app.dependency_overrides[get_db] = lambda: db
    try:
        client = TestClient(app, base_url="https://hocx.example", raise_server_exceptions=False)
        res = client.post(path, content=body.encode(), headers={"content-type": "application/json"})
    finally:
        app.dependency_overrides.pop(get_db, None)
    assert res.status_code < 500, (path, res.status_code, res.text)


@pytest.mark.parametrize(("body", "expected"), [
    (b'{"a": "x\\ud800"}', True),
    (b'{"a": "\\udc00x"}', True),
    (b'{"\\uDBFF": 1}', True),  # auch in Schlüsseln, Grossschreibung
    (b'{"a": "\\ud83d\\ude00"}', False),  # gültiges Paar (Emoji)
    (b'{"a": "\\\\ud800"}', False),  # escapter Backslash: «ud800» ist Text
    (b'{"a": "\\u00e4"}', False),
    (b'{"a": "\\ud800', False),  # kein gültiges JSON: entscheidet FastAPI
])
def test_contains_json_lone_surrogate(body, expected):
    from app.nul_guard import contains_json_lone_surrogate

    assert contains_json_lone_surrogate(body) is expected


def test_valid_surrogate_pair_still_reaches_the_route(db):
    app.dependency_overrides[get_db] = lambda: db
    try:
        client = TestClient(app, base_url="https://hocx.example", raise_server_exceptions=False)
        res = client.post("/api/auth/login", content=b'{"email": "a@example.com", "password": "\\ud83d\\ude00secret"}', headers={"content-type": "application/json"})
    finally:
        app.dependency_overrides.pop(get_db, None)
    assert res.status_code == 401


@pytest.mark.parametrize("content_type", [None, "application/vnd.api+json", "text/json"])
@pytest.mark.parametrize("payload", [
    b'{"email": "a@example.com", "password": "x\\ud800y"}',
    b'{"email": "a@example.com", "password": "x\\u0000y"}',
])
def test_guard_covers_every_body_fastapi_parses_as_json(db, content_type, payload):
    """FastAPI liest auch Bodies mit «+json»-Untertyp als JSON (ohne Content-Type: 422 von FastAPI)."""
    app.dependency_overrides[get_db] = lambda: db
    try:
        client = TestClient(app, base_url="https://hocx.example", raise_server_exceptions=False)
        req = client.build_request("POST", "/api/auth/login", content=payload)
        if content_type is None:
            req.headers.pop("content-type", None)
        else:
            req.headers["content-type"] = content_type
        res = client.send(req)
    finally:
        app.dependency_overrides.pop(get_db, None)
    assert res.status_code < 500, (content_type, res.status_code, res.text)


@pytest.mark.parametrize(("content_type", "expected"), [
    (None, False),  # FastAPI liest ohne Content-Type kein JSON (strict_content_type)
    (b"", False),
    (b"application/json", True),
    (b"Application/JSON; charset=utf-8", True),
    (b"application/vnd.api+json", True),
    (b"application/octet-stream", False),
    (b"multipart/form-data; boundary=x", False),
    (b"text/json", False),
])
def test_parsed_as_json_matches_fastapi(content_type, expected):
    from app.nul_guard import parsed_as_json

    assert parsed_as_json(content_type) is expected


def test_large_json_body_is_streamed_not_buffered():
    """Über der Puffergrenze reicht die Middleware den Body unverändert und vollständig durch
    (Galerie-/Import-Pfade haben kein RequestBodyLimit)."""
    from app.nul_guard import NulGuardMiddleware

    mini = FastAPI()
    mini.add_middleware(NulGuardMiddleware, max_buffer_bytes=1024)

    @mini.post("/api/raw")
    async def raw(request: Request):
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
        return {"size": size}

    def chunks():
        for _ in range(10):
            yield b"x" * 600

    client = TestClient(mini)
    req = client.build_request("POST", "/api/raw", content=chunks())
    req.headers["content-type"] = "application/json"
    res = client.send(req)
    assert res.status_code == 200 and res.json() == {"size": 6000}, res.text
