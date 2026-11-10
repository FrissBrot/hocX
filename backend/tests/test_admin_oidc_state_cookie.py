"""Audit MAIN-SEC-006 (OIDC-Teil): Der Admin-SSO-Callback akzeptiert nur einen state, der
in diesem Browser gestartet wurde."""
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.routes import admin_auth
from app.core.db import get_db


def _client(monkeypatch, calls: list):
    monkeypatch.setattr(
        admin_auth.oidc_service, "build_authorize_url",
        lambda db, base, redirect_to: "https://idp.example.com/auth?state=STATE-123&nonce=x",
    )

    def fake_callback(db, code, state, base):
        calls.append(state)
        raise HTTPException(status_code=418, detail="callback erreicht")

    monkeypatch.setattr(admin_auth.oidc_service, "handle_callback", fake_callback)
    app = FastAPI()
    app.include_router(admin_auth.router, prefix="/api/admin/auth")
    app.dependency_overrides[get_db] = lambda: None
    return TestClient(app, base_url="https://admin.example.com")


def test_callback_without_state_cookie_is_rejected(monkeypatch):
    calls: list = []
    client = _client(monkeypatch, calls)

    response = client.get("/api/admin/auth/oidc/callback", params={"code": "c", "state": "STATE-123"})

    assert response.status_code == 400
    assert calls == []


def test_callback_with_cookie_from_authorize_passes_state_check(monkeypatch):
    calls: list = []
    client = _client(monkeypatch, calls)

    authorize = client.get("/api/admin/auth/oidc/authorize", follow_redirects=False)
    assert authorize.status_code == 302
    assert "hocx_admin_oidc_state" in authorize.headers["set-cookie"]

    other = client.get("/api/admin/auth/oidc/callback", params={"code": "c", "state": "ANDERER"})
    assert other.status_code == 400

    ok = client.get("/api/admin/auth/oidc/callback", params={"code": "c", "state": "STATE-123"})
    assert ok.status_code == 418
    assert calls == ["STATE-123"]
