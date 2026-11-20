"""Auth-Audit SEC-AUTH-001: /api/admin nur über Traefiks Admin-Entrypoint (Gate-Header) und die
Admin-Domain - sonst 404, auch wenn ein Router die Pfade doch einmal durchlässt (app/core/admin_gate.py)."""
from __future__ import annotations

import secrets

import pytest
from fastapi.testclient import TestClient

from app.core import admin_gate
from app.main import app

pytestmark = pytest.mark.admin_gate

ADMIN_DOMAIN = "admin.hocx.example"
PUBLIC_CONFIG = "/api/admin/auth/health"


@pytest.fixture
def gate_secret(monkeypatch) -> str:
    value = secrets.token_hex(32)
    monkeypatch.setattr(admin_gate.settings, "admin_gate_secret", value)
    monkeypatch.setattr(admin_gate.settings, "traefik_admin_domain", ADMIN_DOMAIN)
    return value


def _client(host: str = ADMIN_DOMAIN, client: tuple[str, int] = ("172.18.0.5", 50000)) -> TestClient:
    # Ohne `with`: kein Lifespan, das Gate sitzt ohnehin vor jeder Route.
    return TestClient(app, base_url=f"https://{host}", client=client)


def test_correct_gate_header_on_admin_domain_passes(gate_secret):
    response = _client().get(PUBLIC_CONFIG, headers={"X-Hocx-Admin-Gate": gate_secret})
    assert response.status_code == 200


def test_admin_domain_with_port_passes(gate_secret):
    # traefik_checks.sh prüft den Admin-Entrypoint direkt über 127.0.0.1:8443 (Host mit Port)
    response = _client(host=f"{ADMIN_DOMAIN}:8443").get(PUBLIC_CONFIG, headers={"X-Hocx-Admin-Gate": gate_secret})
    assert response.status_code == 200


@pytest.mark.parametrize("header", [None, "", "falsch", "x" * 64])
def test_missing_or_wrong_gate_header_is_404(gate_secret, header):
    headers = {} if header is None else {"X-Hocx-Admin-Gate": header}
    response = _client().get(PUBLIC_CONFIG, headers=headers)
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_rejection_looks_like_an_unknown_path(gate_secret):
    unknown = _client().get("/api/gibt-es-nicht")
    blocked = _client().post("/api/admin/auth/login", json={"email": "a@b.example", "password": "x"})
    assert blocked.status_code == unknown.status_code == 404
    assert blocked.json() == unknown.json()


@pytest.mark.parametrize("host", ["app.hocx.example", "verein.example.org", "evil.admin.hocx.example", "backend"])
def test_wrong_host_is_404_even_with_correct_header(gate_secret, host):
    response = _client(host=host).get(PUBLIC_CONFIG, headers={"X-Hocx-Admin-Gate": gate_secret})
    assert response.status_code == 404


def test_frontend_server_call_with_forwarded_host_passes(gate_secret):
    """Next.js ruft über http://backend:8000 auf und reicht Gate-Header und Host weiter."""
    response = _client(host="backend:8000").get(
        PUBLIC_CONFIG, headers={"X-Hocx-Admin-Gate": gate_secret, "X-Forwarded-Host": ADMIN_DOMAIN}
    )
    assert response.status_code == 200


def test_forwarded_host_from_untrusted_peer_is_ignored(gate_secret):
    response = _client(host="backend:8000", client=("203.0.113.9", 40000)).get(
        PUBLIC_CONFIG, headers={"X-Hocx-Admin-Gate": gate_secret, "X-Forwarded-Host": ADMIN_DOMAIN}
    )
    assert response.status_code == 404


def test_without_admin_domain_only_the_header_counts(gate_secret, monkeypatch):
    monkeypatch.setattr(admin_gate.settings, "traefik_admin_domain", None)
    ok = _client(host="irgendwo.example").get(PUBLIC_CONFIG, headers={"X-Hocx-Admin-Gate": gate_secret})
    blocked = _client(host="irgendwo.example").get(PUBLIC_CONFIG)
    assert (ok.status_code, blocked.status_code) == (200, 404)


def test_non_admin_paths_are_not_affected(gate_secret):
    assert _client(host="app.hocx.example").get("/api/health").status_code == 200
    # Nur das ganze Pfadsegment: /api/administration wäre keine Admin-API
    assert admin_gate.is_admin_api_path("/api/admin")
    assert admin_gate.is_admin_api_path("/api/admin/x")
    assert not admin_gate.is_admin_api_path("/api/administration")


@pytest.mark.parametrize("environment", ["development", "dev", "local", "DEVELOPMENT"])
def test_development_without_secret_is_open(monkeypatch, environment):
    monkeypatch.setattr(admin_gate.settings, "admin_gate_secret", None)
    monkeypatch.setattr(admin_gate.settings, "environment", environment)
    monkeypatch.setattr(admin_gate.settings, "traefik_admin_domain", ADMIN_DOMAIN)
    assert admin_gate.gate_mode() == admin_gate.MODE_OPEN
    assert _client(host="localhost").get(PUBLIC_CONFIG).status_code == 200


@pytest.mark.parametrize("environment", ["production", "prod", "test", ""])
def test_release_environment_without_secret_fails_closed(monkeypatch, environment):
    monkeypatch.setattr(admin_gate.settings, "admin_gate_secret", None)
    monkeypatch.setattr(admin_gate.settings, "environment", environment)
    monkeypatch.setattr(admin_gate.settings, "traefik_admin_domain", ADMIN_DOMAIN)
    assert admin_gate.gate_mode() == admin_gate.MODE_CLOSED
    # Auch ein beliebiger Header öffnet nichts
    response = _client().get(PUBLIC_CONFIG, headers={"X-Hocx-Admin-Gate": ""})
    assert response.status_code == 404


def test_closed_gate_is_recorded_in_error_log(monkeypatch):
    monkeypatch.setattr(admin_gate.settings, "admin_gate_secret", None)
    monkeypatch.setattr(admin_gate.settings, "environment", "production")
    recorded: list[Exception] = []
    import app.core.error_log as error_log

    monkeypatch.setattr(error_log, "record_system_error", lambda db, *, exc, **_kw: recorded.append(exc))
    admin_gate.log_gate_configuration()
    assert len(recorded) == 1
    assert "ADMIN_GATE_SECRET" in str(recorded[0])


def test_websocket_under_admin_api_is_rejected(gate_secret):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with _client().websocket_connect("/api/admin/ws-test"):
            pass
