"""Plattform-Admin im Anmeldeschutz (Integration fix/admin-isolation + feat/auth-hardening).

- Passwortphase über LoginGuard (Scope login-admin, ohne IP-Sperren - Ziti-Notzugang).
- Sicherheitsereignisse admin.login.password/.mfa/.success, admin.mfa.enroll, admin.stepup,
  admin.logout; die Alarmregeln admin_new_device und admin_mfa greifen darauf.
- Passkey-Versuche vor der Prüfung gezählt (consume_factor_attempt, principal admin).
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException, Request, Response
from sqlalchemy import select

from app.auth_security import devices, threats
from app.core.admin_security import CurrentAdmin
from app.core.redis_client import get_redis_sync
from app.models import AuthEvent
from app.models.entities import PlatformAdmin
from app.schemas.admin import AdminLoginRequest
from app.services import admin_mfa_service as mfa_module
from app.services.admin_auth_service import AdminAuthService
from app.services.admin_mfa_service import clear_admin_lockouts
from app.core import rate_limit
from tests.soft_passkey import SoftPasskey

RP_ID = "admin.hocx.example"
ORIGIN = f"https://{RP_ID}"
PASSWORD = "admin-password-lang"


def _flush() -> None:
    client = get_redis_sync()
    for pattern in ("ratelimit:*", "authsec:*", "authblock:*", "admin-mfa:flow:*"):
        for key in client.scan_iter(pattern):
            client.delete(key)
    rate_limit.local_window.clear()


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    monkeypatch.setattr(mfa_module.settings, "traefik_admin_domain", RP_ID)
    _flush()
    yield
    _flush()


@pytest.fixture
def admin(db):
    from app.core.security import hash_password

    row = PlatformAdmin(email=f"events-{id(db)}@example.com", password_hash=hash_password(PASSWORD), display_name="Ops")
    db.add(row)
    db.flush()
    return row


def _request(cookies: dict[str, str] | None = None) -> Request:
    header = "; ".join(f"{name}={value}" for name, value in (cookies or {}).items())
    return Request({"type": "http", "method": "POST", "path": "/api/admin/auth/login", "query_string": b"", "headers": [(b"cookie", header.encode())] if header else []})


def _events(db, admin_id: int, event_type: str) -> list[AuthEvent]:
    db.expire_all()
    return list(db.scalars(select(AuthEvent).where(AuthEvent.platform_admin_id == admin_id, AuthEvent.event_type == event_type).order_by(AuthEvent.id)))


def _device_cookie(response: Response) -> dict[str, str]:
    for name, value in response.raw_headers:
        if name == b"set-cookie" and value.decode().startswith(devices.cookie_name() + "="):
            return {devices.cookie_name(): value.decode().split("=", 1)[1].split(";", 1)[0]}
    return {}


def _login(db, email: str, password: str = PASSWORD, cookies: dict | None = None):
    return AdminAuthService().login(db, Response(), AdminLoginRequest(email=email, password=password), client_address="203.0.113.20", request=_request(cookies))


def _enroll(db, admin: PlatformAdmin, passkey: SoftPasskey) -> Response:
    pending = _login(db, admin.email)
    service = AdminAuthService()
    start = service.start_login_passkey_setup(db, ticket=pending.mfa.ticket, request_host="ignored", request_origin=ORIGIN)
    response = Response()
    service.complete_login_passkey_setup(
        db, response, flow_token=start.flow_token, label="Key", credential=passkey.create(start.public_key, origin=ORIGIN), request=_request()
    )
    return response


def _passkey_login(db, admin: PlatformAdmin, passkey: SoftPasskey, cookies: dict | None = None) -> Response:
    pending = _login(db, admin.email, cookies=cookies)
    service = AdminAuthService()
    start = service.start_login_passkey(db, ticket=pending.mfa.ticket, request_host=None, request_origin=ORIGIN)
    response = Response()
    service.verify_login_passkey(db, response, flow_token=start.flow_token, credential=passkey.get(start.public_key, origin=ORIGIN), request=_request(cookies))
    return response


def test_password_failure_and_success_are_security_events(db, admin):
    with pytest.raises(HTTPException) as exc_info:
        _login(db, admin.email, password="falsch-falsch")
    assert exc_info.value.status_code == 401
    pending = _login(db, admin.email)
    assert pending.authenticated is False

    outcomes = [event.outcome for event in _events(db, admin.id, "admin.login.password")]
    assert outcomes == ["failure", "success"]
    assert all(event.actor_kind == "admin" for event in _events(db, admin.id, "admin.login.password"))


def test_new_device_alarm_only_for_unknown_devices(db, admin):
    passkey = SoftPasskey()
    first = _enroll(db, admin, passkey)
    cookies = _device_cookie(first)
    assert cookies, "Login setzt ein Geräte-Cookie auf der Admin-Domain"
    assert [e.event_type for e in _events(db, admin.id, "admin.mfa.enroll")] == ["admin.mfa.enroll"]

    _passkey_login(db, admin, passkey, cookies=cookies)       # bekanntes Gerät
    _passkey_login(db, admin, passkey)                         # anderes Gerät (kein Cookie)

    success = _events(db, admin.id, "admin.login.success")
    assert [event.details.get("new_device") for event in success] == [True, False, True]
    rules = {(threat.rule, threat.subject) for threat in threats.detect(db)}
    assert ("admin_new_device", str(admin.id)) in rules


def test_failed_passkeys_trigger_admin_mfa_alarm_and_are_counted_before_checking(db, admin, monkeypatch):
    _enroll(db, admin, SoftPasskey())
    monkeypatch.setattr(mfa_module.settings, "auth_passkey_account_limit", 3)
    monkeypatch.setattr(mfa_module.settings, "auth_alert_admin_mfa_failures", 3)
    service = AdminAuthService()
    stranger = SoftPasskey()

    def attempt() -> int:
        pending = _login(db, admin.email)
        start = service.start_login_passkey(db, ticket=pending.mfa.ticket, request_host=None, request_origin=ORIGIN)
        with pytest.raises(HTTPException) as exc_info:
            service.verify_login_passkey(db, Response(), flow_token=start.flow_token, credential=stranger.get(start.public_key, origin=ORIGIN))
        return exc_info.value.status_code

    # Bis zur Grenze und ein Versuch per Drip: geprüft (401), danach gesperrt (429)
    assert [attempt() for _ in range(4)] == [401, 401, 401, 401]
    assert attempt() == 429

    failures = _events(db, admin.id, "admin.login.mfa")
    assert [event.outcome for event in failures][:4] == ["failure"] * 4
    assert any(event.outcome == "blocked" for event in failures)
    assert ("admin_mfa", str(admin.id)) in {(threat.rule, threat.subject) for threat in threats.detect(db)}

    # Notausgang setzt die Zähler zurück
    clear_admin_lockouts(admin)
    assert attempt() == 401


def test_logout_is_recorded(db, admin):
    AdminAuthService().logout(db, Response(), CurrentAdmin(admin_id=admin.id, admin_public_id=admin.public_id, email=admin.email, display_name="Ops"))
    assert [event.outcome for event in _events(db, admin.id, "admin.logout")] == ["success"]


def test_account_limit_locks_admin_login_even_with_the_right_password(db, admin, monkeypatch):
    """Review-Fund 1: harte Grenze je Admin-Konto (wie früher check_login_lockout), vor der
    Passwortprüfung - verteiltes Raten endet, auch das richtige Passwort hilft dann nicht."""
    monkeypatch.setattr(mfa_module.settings, "auth_account_failures_known_only", 3)
    for _ in range(3):
        with pytest.raises(HTTPException) as exc_info:
            _login(db, admin.email, password="falsch-falsch")
        assert exc_info.value.status_code == 401
    with pytest.raises(HTTPException) as exc_info:
        _login(db, admin.email)
    assert exc_info.value.status_code == 429 and exc_info.value.detail["code"] == "login_locked"
    clear_admin_lockouts(admin)
    assert _login(db, admin.email).authenticated is False  # wieder bis zum Passkey


def test_source_limit_does_not_block_the_admin_emergency_access(db, admin, monkeypatch):
    """Review-Fund 2: exempt_from_source_blocks deckt auch die harte Quellgrenze (L1) ab - viele
    Fehlversuche von der Ziti-Quelle sperren den Admin-Login dieser Quelle nicht."""
    monkeypatch.setattr(mfa_module.settings, "auth_ip_failures_hard", 2)
    for index in range(4):
        with pytest.raises(HTTPException) as exc_info:
            _login(db, f"fremd-{index}@example.com", password="falsch-falsch")
        assert exc_info.value.status_code == 401
    assert _login(db, admin.email).authenticated is False
