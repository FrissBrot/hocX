"""NUL-Zeichen zentral abfangen (Nachtlauf 2026-11-20: Muster in ca. 20 Routen) und skip/offset
überall begrenzen.

Ohne NulGuardMiddleware lief ein NUL in Pfad, Query oder JSON-Body bis in PostgreSQL (DataError:
500 bzw. 400 plus Fehlerprotokoll). Jetzt 422 vor jeder Route; Dateien in Multipart bleiben
unberührt."""
from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.nul_guard import NulGuardMiddleware, contains_json_nul


def _client() -> TestClient:
    app = FastAPI()
    app.add_middleware(NulGuardMiddleware)

    @app.post("/api/echo")
    async def echo(request: Request):
        return {"body": (await request.body()).decode("utf-8", "replace")}

    @app.get("/api/search")
    def search(q: str = ""):
        return {"q": q}

    @app.get("/api/items/{slug}")
    def item(slug: str):
        return {"slug": slug}

    @app.post("/api/upload")
    async def upload(request: Request):
        return {"size": len(await request.body())}

    @app.post("/other/echo")
    async def other(request: Request):
        return {"size": len(await request.body())}

    return TestClient(app)


@pytest.mark.parametrize(("body", "expected"), [
    (b'{"title": "a\\u0000b"}', True),
    (b'{"title": "a\\\\\\u0000b"}', True),  # escapter Backslash, dann echtes NUL
    (b'{"title": "a\\\\u0000b"}', False),  # escapter Backslash, «u0000» ist Text
    (b'{"title": "a\\u0001b"}', False),
    (b'{"title": "a\x00b"}', True),
    (b'{"title": "ok"}', False),
])
def test_contains_json_nul(body, expected):
    assert contains_json_nul(body) is expected


def test_json_body_with_nul_is_rejected_before_the_route():
    client = _client()
    response = client.post("/api/echo", content=b'{"title": "a\\u0000b"}', headers={"Content-Type": "application/json"})
    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "string_nul"


def test_clean_json_body_reaches_the_route_unchanged():
    client = _client()
    body = '{"title": "a\\\\u0000b", "x": "ä"}'
    response = client.post("/api/echo", content=body.encode(), headers={"Content-Type": "application/json; charset=utf-8"})
    assert response.status_code == 200
    assert response.json()["body"] == body


def test_query_and_path_with_nul_are_rejected():
    client = _client()
    assert client.get("/api/search?q=a%00b").status_code == 422
    assert client.get("/api/items/a%00b").status_code == 422
    assert client.get("/api/search?q=ab").json() == {"q": "ab"}


def test_binary_uploads_and_other_paths_are_untouched():
    client = _client()
    assert client.post("/api/upload", content=b"\x00\x01\x00", headers={"Content-Type": "application/octet-stream"}).json() == {"size": 3}
    assert client.post("/other/echo", content=b'{"a": "\\u0000"}', headers={"Content-Type": "application/json"}).json() == {"size": 15}


def test_main_app_has_the_guard():
    from app.main import app

    assert any(middleware.cls is NulGuardMiddleware for middleware in app.user_middleware)


def test_every_skip_and_offset_query_has_an_upper_bound():
    """skip/offset gehen als OFFSET an PostgreSQL: ohne Obergrenze «bigint out of range» (500)."""
    from app.main import app

    missing = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for param in route.dependant.query_params:
            if param.name not in {"skip", "offset"}:
                continue
            bounded = any(getattr(item, "le", None) is not None or getattr(item, "lt", None) is not None for item in param.field_info.metadata)
            if not bounded:
                missing.append(f"{','.join(route.methods)} {route.path} ({param.name})")
    assert missing == []
