"""Kaputter Origin-Header (Nachtlauf 2026-11-26, auth-session/eingaben).

``urlsplit("http://[")`` wirft ValueError («Invalid IPv6 URL»). Die CSRF-Middleware rief das für
jeden zustandsändernden Request ungeschützt auf: ein einziger Header genügte, um ohne Anmeldung
auf jeder POST-Route einen 500 samt Eintrag im Fehlerprotokoll auszulösen. Erwartet: ein nicht
lesbarer Origin ist eine fremde Herkunft (403), auch für die GET-Route der Step-up-Optionen
(400 statt 500)."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.origin_guard import OriginGuardMiddleware, origin_allowed
from app.core.security import get_current_user
from app.main import app
from tests.factories import make_current_user, make_tenant

MALFORMED = ["http://[", "https://[::1", "http://]x["]


@pytest.mark.parametrize("origin", MALFORMED)
def test_origin_allowed_rejects_unparsable_origin(origin):
    assert origin_allowed(origin, host="example.test", forwarded_host=None, allowed_origins=set()) is False


@pytest.mark.parametrize("origin", MALFORMED)
def test_middleware_answers_403_for_unparsable_origin(origin):
    mini = FastAPI()
    mini.add_middleware(OriginGuardMiddleware, allowed_origins=set())

    @mini.post("/api/echo")
    def echo():
        return {"ok": True}

    response = TestClient(mini, raise_server_exceptions=False).post("/api/echo", headers={"Origin": origin})
    assert response.status_code == 403


def test_public_login_route_answers_403_not_500():
    client = TestClient(app, raise_server_exceptions=False)
    response = client.post("/api/auth/password-reset/request", json={"email": "x@example.com"}, headers={"Origin": "http://["})
    assert response.status_code == 403


def test_step_up_options_with_unparsable_origin_is_400(db):
    tenant = make_tenant(db)
    app.dependency_overrides[get_current_user] = lambda: make_current_user(tenant.id, role="writer")
    try:
        response = TestClient(app, raise_server_exceptions=False).get("/api/auth/step-up", headers={"Origin": "http://["})
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    assert response.status_code == 400
