"""Anmeldeschutz (Auth-Audit 2026-11-20, /docker/audit-reports/auth-security-2026-11-20).

Die Nachweistests des Audits (test_auth_audit.py) invertiert als Regressionstests plus die
Testfälle T1-T18 aus Abschnitt 13, soweit sie ohne Traefik/OIDC lokal machbar sind:
- T5 (XFF-Spoofing) deckt tests/test_login_lockout_per_ip.py ab,
- T12 (Admin-API über Mandanten-Domain) und T16 (OIDC amr) gehören zum Branch fix/admin-isolation.

Alles läuft gegen das echte Redis des Teststacks (Lua-Skripte, HLL, GCRA).
"""
from __future__ import annotations

import base64
import json
import re
import secrets
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
import redis as redis_sync
from fastapi import HTTPException, Response
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from starlette.requests import Request

from app.auth_security import blocks, devices, events, risk, sessions, threats
from app.auth_security.guard import LoginGuard
from app.core import rate_limit
from app.core.auth_pseudonym import source_address, subject_hash
from app.core.config import settings
from app.core.db import SessionLocal, get_db
from app.core.redis_client import get_redis_sync
from app.core.secret_crypto import encrypt_secret
from app.core.security import build_current_user, create_session_token, get_optional_current_user, hash_password, parse_session_token, validate_session_token
from app.core.totp import current_totp_code, generate_totp_secret
from app.models import AppUser, AuthEvent, AuthSession, Notification, Tenant, UserMfaFactor
from app.notifications import email_transport
from app.schemas.mfa import TotpLoginVerifyRequest
from app.schemas.user import LoginRequest
from app.services.auth_service import AuthService
from app.services.mfa_service import MfaService
from app.services.notification_settings_service import NotificationSettingsService
from tests.factories import make_app_user, make_mfa_enrolled_user, make_tenant

PASSWORD = "correct horse battery staple"


def _flush() -> None:
    client = get_redis_sync()
    for pattern in ("ratelimit:*", "authsec:*", "authblock:*", "mfa:flow:*", "domain_bridge_*"):
        for key in client.scan_iter(pattern):
            client.delete(key)
    rate_limit.local_window.clear()


@pytest.fixture(autouse=True)
def _clean():
    _flush()
    yield
    _flush()


def _req(cookies: dict[str, str] | None = None) -> Request:
    header = "; ".join(f"{name}={value}" for name, value in (cookies or {}).items())
    return Request({"type": "http", "method": "POST", "path": "/api/auth/login", "query_string": b"", "headers": [(b"cookie", header.encode())] if header else []})


def _login(db, email: str, password: str = PASSWORD, *, ip: str = "203.0.113.10", cookies: dict | None = None):
    response = Response()
    result = AuthService().login(db, response, LoginRequest(email=email, password=password), client_address=ip, request=_req(cookies))
    return result, response


def _set_cookies(response: Response) -> dict[str, str]:
    cookies = {}
    for header in response.headers.getlist("set-cookie"):
        name, _, rest = header.partition("=")
        value = rest.split(";", 1)[0]
        if value:
            cookies[name] = value.strip('"')
    return cookies


def _session_token(response: Response) -> str:
    cookies = _set_cookies(response)
    return next(value for name, value in cookies.items() if name.endswith("hocx_session"))


def _known_device(db, user) -> dict[str, str]:
    device_id = devices.new_device_id()
    devices.remember(db, user_id=user.id, tenant_id=user.tenant_id, device_id=device_id, user_agent_family="Firefox · Linux")
    db.flush()
    return {devices.cookie_name(): devices.encode_cookie(device_id)}


@pytest.fixture
def mail(db):
    row = NotificationSettingsService().get_row(db)
    row.email_enabled = True
    row.smtp_host = "smtp.example.com"
    row.email_from_address = "noreply@example.com"
    row.email_link_base_url = "https://app.example.com"
    db.flush()
    sent: list = []
    email_transport.override_transport(lambda config, email: sent.append(email))
    yield sent
    email_transport.override_transport(None)


_COMMITTED_TENANTS: list[int] = []


@pytest.fixture(autouse=True)
def _remove_committed_tenants():
    """Für die Nebenläufigkeitstests echt committete Konten wieder entfernen (sonst sähen andere
    Tests Mandanten ohne die Standarddaten)."""
    yield
    if _COMMITTED_TENANTS:
        with SessionLocal() as session:
            session.execute(text("DELETE FROM auth_session WHERE tenant_id = ANY(:ids)"), {"ids": _COMMITTED_TENANTS})
            session.execute(text("DELETE FROM auth_known_device WHERE tenant_id = ANY(:ids)"), {"ids": _COMMITTED_TENANTS})
            session.execute(text("DELETE FROM user_mfa_factor WHERE user_id IN (SELECT id FROM app_user WHERE tenant_id = ANY(:ids))"), {"ids": _COMMITTED_TENANTS})
            session.execute(text("DELETE FROM user_role WHERE user_id IN (SELECT id FROM app_user WHERE tenant_id = ANY(:ids))"), {"ids": _COMMITTED_TENANTS})
            session.execute(text("DELETE FROM app_user WHERE tenant_id = ANY(:ids)"), {"ids": _COMMITTED_TENANTS})
            session.execute(text("DELETE FROM tenant WHERE id = ANY(:ids)"), {"ids": _COMMITTED_TENANTS})
            session.commit()
        _COMMITTED_TENANTS.clear()


def _committed_user(email: str, *, totp_secret: str | None = None) -> int:
    with SessionLocal() as session:
        tenant = Tenant(name=f"Härtung {uuid.uuid4().hex[:6]}")
        session.add(tenant)
        session.flush()
        _COMMITTED_TENANTS.append(tenant.id)
        user = AppUser(tenant_id=tenant.id, email=email, password_hash=hash_password(PASSWORD), login_enabled=True,
                       first_name="A", last_name="B", display_name="A B", is_active=True)
        session.add(user)
        session.flush()
        if totp_secret:
            session.add(UserMfaFactor(user_id=user.id, factor_type="totp", label="t", secret_encrypted=encrypt_secret(totp_secret)))
        session.commit()
        return user.id


def _events(db, **filters) -> list[AuthEvent]:
    db.expire_all()
    statement = select(AuthEvent)
    for name, value in filters.items():
        statement = statement.where(getattr(AuthEvent, name) == value)
    return list(db.scalars(statement.order_by(AuthEvent.id)))


# ── SEC-AUTH-002 (B1 invertiert, T11) ───────────────────────────────────


def test_oversized_login_is_rejected_before_redis(db):
    from app.main import app

    app.dependency_overrides[get_db] = lambda: db
    try:
        client = TestClient(app, base_url="https://hocx.example", raise_server_exceptions=False)
        before = len(list(get_redis_sync().scan_iter("ratelimit:*")))
        res = client.post("/api/auth/login", json={"email": "a" * 321 + "@example.com", "password": "x"})
        assert res.status_code == 422
        res = client.post("/api/auth/login", json={"email": "a@example.com", "password": "x" * 1025})
        assert res.status_code == 422
        # Kleines Body-Limit für /api/auth/* (16 KiB) statt 10 MiB
        res = client.post("/api/auth/login", content=json.dumps({"email": "a" * 20000, "password": "x"}), headers={"content-type": "application/json"})
        assert res.status_code == 413
        assert len(list(get_redis_sync().scan_iter("ratelimit:*"))) == before
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_admin_login_passkey_routes_get_the_passkey_body_limit():
    """Admin-Passkey beim Login (admin-isolation: /api/admin/auth/mfa/passkey/…): Attestation mit
    Zertifikatskette braucht das grössere Limit, der Rest von /api/admin/auth das kleine."""
    from app.core.config import settings
    from app.main import app
    from app.request_body_limit import RequestBodyLimitMiddleware

    (middleware,) = [m for m in app.user_middleware if m.cls is RequestBodyLimitMiddleware]
    limits = middleware.kwargs["path_limits"]

    def limit_for(path: str) -> int | None:
        return next((value for prefix, value in limits if path.startswith(prefix)), None)

    for path in (
        "/api/admin/auth/mfa/passkey/setup/start", "/api/admin/auth/mfa/passkey/setup/complete",
        "/api/admin/auth/mfa/passkey/start", "/api/admin/auth/mfa/passkey/verify",
    ):
        assert limit_for(path) == settings.auth_passkey_max_request_body_bytes, path
    assert limit_for("/api/admin/auth/login") == settings.auth_max_request_body_bytes


def test_rate_limit_keys_are_short_hmacs_without_email_or_ip(db):
    email = "Klartext.Person@example.com"
    with pytest.raises(HTTPException):
        _login(db, email, "falsch", ip="198.51.100.77")
    keys = list(get_redis_sync().scan_iter("ratelimit:*"))
    assert keys
    for key in keys:
        assert len(key) <= 100, key
        assert "example.com" not in key.lower() and "198.51.100" not in key


def test_limiter_fails_closed_with_503_when_redis_is_full(monkeypatch):
    def full(*_args, **_kwargs):
        raise redis_sync.exceptions.ResponseError("OOM command not allowed when used memory > 'maxmemory'.")

    monkeypatch.setattr(rate_limit, "_script", lambda *_a: (full, None))
    with pytest.raises(HTTPException) as exc:
        rate_limit.enforce_rate_limit("password-reset-ip:1.2.3.4", limit=10, period_seconds=60)
    assert exc.value.status_code == 503
    assert exc.value.detail["code"] == "rate_limiter_unavailable"
    # fail_open: lokale Notgrenze statt 503
    rate_limit.enforce_rate_limit("tenant-by-domain:1.2.3.4", limit=2, period_seconds=60, fail_open=True)
    rate_limit.enforce_rate_limit("tenant-by-domain:1.2.3.4", limit=2, period_seconds=60, fail_open=True)
    with pytest.raises(HTTPException) as exc:
        rate_limit.enforce_rate_limit("tenant-by-domain:1.2.3.4", limit=2, period_seconds=60, fail_open=True)
    assert exc.value.status_code == 429


# ── SEC-AUTH-003/-005 (C1, C2, D1 invertiert; T1, T10) ─────────────────


def test_T1_parallel_password_guesses_never_exceed_the_limit():
    email = f"race-{uuid.uuid4().hex[:8]}@example.com"
    _committed_user(email)
    barrier = threading.Barrier(40)

    def attempt(index: int) -> int:
        with SessionLocal() as session:
            barrier.wait()
            try:
                _login(session, email, f"falsch-{index}", ip="203.0.113.77")
            except HTTPException as exc:
                return exc.status_code
        return 200

    with ThreadPoolExecutor(40) as pool:
        codes = list(pool.map(attempt, range(40)))
    assert codes.count(401) <= settings.auth_account_ip_failures
    assert codes.count(429) >= 40 - settings.auth_account_ip_failures


def test_C2_parallel_totp_guesses_over_several_tickets_respect_the_account_limit():
    secret = generate_totp_secret()
    user_id = _committed_user(f"totp-race-{uuid.uuid4().hex[:8]}@example.com", totp_secret=secret)
    service = MfaService()
    tickets = [service._create_flow("login_ticket", {"user_id": user_id, "request_host": None, "issued_at": int(time.time()) + 5}) for _ in range(4)]
    barrier = threading.Barrier(40)

    def attempt(index: int) -> int:
        with SessionLocal() as session:
            barrier.wait()
            try:
                MfaService().verify_login_totp(session, ticket=tickets[index % 4], code=f"{(index * 7919) % 1000000:06d}")
            except HTTPException as exc:
                return exc.status_code
        return 200

    with ThreadPoolExecutor(40) as pool:
        codes = list(pool.map(attempt, range(40)))
    # Grenze + höchstens ein «Drip»-Versuch je Minute
    assert codes.count(401) <= settings.auth_totp_account_limit + 1


def test_T10_counters_always_get_a_ttl_and_old_keys_are_repaired():
    client = get_redis_sync()
    rate_limit.record_failed_attempt("legacy-scope:subject", period_seconds=900)
    key = rate_limit._legacy_key("legacy-scope:subject")
    assert 0 < client.ttl(key) <= 900
    # Altlast ohne TTL (vor dem Update entstanden) wird beim nächsten Zählen repariert
    client.persist(key)
    assert client.ttl(key) == -1
    rate_limit.record_failed_attempt("legacy-scope:subject", period_seconds=900)
    assert client.ttl(key) > 0
    client.set("ratelimit:manual-no-ttl", "5")
    assert rate_limit.repair_keys_without_ttl() >= 1
    assert client.ttl("ratelimit:manual-no-ttl") > 0
    for counter_key in client.scan_iter("ratelimit:*"):
        assert client.ttl(counter_key) > 0


# ── SEC-AUTH-004 (C3 invertiert, T7) ────────────────────────────────────


def test_T7_same_totp_code_is_never_accepted_twice_in_parallel():
    doubles = 0
    for _ in range(12):
        secret = generate_totp_secret()
        user_id = _committed_user(f"replay-{uuid.uuid4().hex[:8]}@example.com", totp_secret=secret)
        service = MfaService()
        tickets = [service._create_flow("login_ticket", {"user_id": user_id, "request_host": None, "issued_at": int(time.time()) + 5}) for _ in range(2)]
        code = current_totp_code(secret)
        barrier = threading.Barrier(2)

        def attempt(index: int) -> int:
            with SessionLocal() as session:
                barrier.wait()
                try:
                    MfaService().verify_login_totp(session, ticket=tickets[index], code=code)
                    return 200
                except HTTPException as exc:
                    return exc.status_code

        with ThreadPoolExecutor(2) as pool:
            if list(pool.map(attempt, range(2))) == [200, 200]:
                doubles += 1
    assert doubles == 0


# ── SEC-AUTH-006 (E1 invertiert, T6) und SEC-AUTH-007 (T4) ──────────────


def test_T6_known_device_still_logs_in_after_a_lockout_attack(db):
    tenant = make_tenant(db)
    user = make_app_user(db, email="victim-dos@example.com", tenant_id=tenant.id, role_code="writer")
    cookies = _known_device(db, user)
    for net in range(11):
        for _ in range(10):
            with pytest.raises(HTTPException):
                _login(db, user.email, "falsch", ip=f"2001:db8:{net}:1::1")
    # Ohne bekanntes Gerät: abgewiesen
    with pytest.raises(HTTPException) as exc:
        _login(db, user.email, ip="198.51.100.200")
    assert exc.value.status_code == 429
    # Inhaberin auf ihrem Gerät: angemeldet
    result, response = _login(db, user.email, ip="198.51.100.201", cookies=cookies)
    assert result.authenticated
    # Gesperrte Versuche sind sichtbar (SEC-AUTH-012), aber gesampelt
    assert _events(db, event_type="login.locked", subject_hash=subject_hash(user.email))


def test_T4_ipv6_rotation_within_a_64_counts_as_one_source(db):
    tenant = make_tenant(db)
    user = make_app_user(db, email="ipv6-rotation@example.com", tenant_id=tenant.id)
    codes = []
    for suffix in range(1, 16):
        try:
            _login(db, user.email, "falsch", ip=f"2001:db8:1:1::{suffix:x}")
        except HTTPException as exc:
            codes.append(exc.status_code)
    assert codes.count(401) == settings.auth_account_ip_failures
    assert codes[-1] == 429


def test_T2_spraying_from_one_ip_is_throttled_and_detected(db, monkeypatch):
    monkeypatch.setattr("app.services.auth_service.verify_password", lambda *_args: False)
    monkeypatch.setattr(settings, "auth_ip_attempts_burst", 1000)
    codes = []
    for index in range(80):
        try:
            _login(db, f"spray-{index}@example.com", "Sommer2026!", ip="192.0.2.50")
        except HTTPException as exc:
            codes.append(exc.status_code)
    # ab der weichen Schwelle (20) zusätzliche Prüfung - ohne E-Mail-Versand abgewiesen
    assert codes.count(401) <= settings.auth_ip_failures_soft
    assert codes[-1] == 429
    assert any(threat.rule == "spraying" for threat in threats.detect(db))


def test_T3_stuffing_turns_on_attack_mode_and_alarms(db, monkeypatch):
    monkeypatch.setattr("app.services.auth_service.verify_password", lambda *_args: False)
    for index in range(settings.auth_global_attack_min + 5):
        with pytest.raises(HTTPException):
            _login(db, f"stuffing-{index}@example.com", "Leak-Passwort-1", ip=f"198.18.{index % 250}.{1 + index // 250}")
    check = LoginGuard().check(email="neu@example.com", ip="203.0.113.99", known_device=False, device_hash=None)
    assert check.signals.attack_mode
    assert check.force_verification
    assert any(threat.rule == "stuffing" and threat.severity == "critical" for threat in threats.detect(db))


def test_T14_club_meeting_behind_one_nat_gets_no_hard_lock(db, mail, monkeypatch):
    """50 Anmeldungen + 30 Tippfehler hinter einer NAT-Adresse: höchstens zusätzliche Prüfung
    (E-Mail-Code), keine harte Sperre."""
    monkeypatch.setattr(settings, "auth_ip_attempts_burst", 1000)
    tenant = make_tenant(db)
    users = [make_app_user(db, email=f"mitglied-{index}@example.com", tenant_id=tenant.id) for index in range(50)]
    hard = 0
    for index, user in enumerate(users):
        if index < 30:
            with pytest.raises(HTTPException) as exc:
                _login(db, user.email, "Tippfehler", ip="100.64.1.1")
            hard += exc.value.detail.get("code") in ("login_locked", "source_blocked") if isinstance(exc.value.detail, dict) else 0
        result, _ = _login(db, user.email, ip="100.64.1.1")
        assert result.authenticated or (result.mfa and result.mfa.status == "email_verification_required")
    assert hard == 0


def test_attempt_rate_per_source_is_limited_in_the_app(db, monkeypatch):
    """Auch auf Mandanten-Domains (ohne Traefik-Regel) bremst die App die Versuchsrate je Quelle."""
    monkeypatch.setattr("app.services.auth_service.verify_password", lambda *_args: False)
    codes = []
    for index in range(settings.auth_ip_attempts_burst + 5):
        try:
            _login(db, f"rate-{index}@example.com", "falsch", ip="192.0.2.80")
        except HTTPException as exc:
            codes.append(exc.detail["code"])
    assert "rate_limited" in codes


# ── Stufenmodell IP-Sperren (Abschnitt 8) ───────────────────────────────


def test_repeated_hard_limits_block_the_source_and_unblock_works(db, monkeypatch):
    monkeypatch.setattr(settings, "auth_block_strikes", 2)
    for _ in range(2):
        assert blocks.strike("192.0.2.200", reason="test") is None or True
    block = blocks.is_blocked("192.0.2.200")
    assert block is not None and block.stage == 4 and block.until - time.time() <= 60 * 60 + 5
    with pytest.raises(HTTPException) as exc:
        _login(db, "irgendwer@example.com", "x", ip="192.0.2.200")
    assert exc.value.detail["code"] == "source_blocked"
    assert blocks.clear(block.subject)
    assert blocks.is_blocked("192.0.2.200") is None
    assert _events(db, event_type="block.set") and _events(db, event_type="block.clear")


# ── Risk Engine v1 (Abschnitt 7) ────────────────────────────────────────


def test_risk_engine_is_deterministic_and_explainable():
    normal = risk.assess(risk.Signals(known_device=True))
    assert (normal.score, normal.level, normal.reasons) == (0, risk.NORMAL, [])
    new_device = risk.assess(risk.Signals())
    assert new_device.reasons == ["new_device"] and new_device.level == risk.NORMAL
    moderate = risk.assess(risk.Signals(new_network=True, privileged=True))
    assert moderate.level == risk.MODERATE and set(moderate.reasons) == {"new_device", "new_network", "privileged_account"}
    critical = risk.assess(risk.Signals(account_failures=30, source_failures=60, accounts_from_net=12, attack_mode=True))
    assert critical.level == risk.CRITICAL and critical.score <= 100
    # Fälschbare Merkmale wiegen wenig, bekannte Geräte bekommen keinen Angriffsmodus-Zuschlag
    assert "attack_mode" not in risk.assess(risk.Signals(known_device=True, attack_mode=True)).reasons


def test_risky_login_without_factor_requires_an_email_code(db, mail):
    tenant = make_tenant(db)
    user = make_app_user(db, email="risky@example.com", tenant_id=tenant.id, role_code="admin")
    # Zuerst eine normale Anmeldung (Baseline), dann von einem neuen Netz
    events.record(event_type="login.success", outcome="success", user_id=user.id, tenant_id=tenant.id)
    db.execute(text("UPDATE auth_event SET src_net_hash = 'bekanntes-netz' WHERE actor_user_id = :id"), {"id": user.id})
    db.commit()
    # admin ohne Faktor: Pflicht -> Einrichtung; vorher aber E-Mail-Code (neues Gerät, neues Netz, Adminrechte)
    result, _ = _login(db, user.email, ip="203.0.113.150")
    assert not result.authenticated
    assert result.mfa.status == "email_verification_required"
    code = re.search(r"\b(\d{6})\b", mail[-1].text).group(1)
    assert "203.0.113" not in mail[-1].text and "#token" not in mail[-1].text
    from app.schemas.mfa import EmailChallengeVerifyRequest

    with pytest.raises(HTTPException) as exc:
        AuthService().verify_email_challenge(db, Response(), EmailChallengeVerifyRequest(ticket=result.mfa.ticket, code="000000" if code != "000000" else "111111"))
    assert exc.value.detail["code"] == "email_code_invalid"
    after = AuthService().verify_email_challenge(db, Response(), EmailChallengeVerifyRequest(ticket=result.mfa.ticket, code=code))
    # Danach: Ersteinrichtung des zweiten Faktors (MFA-Pflicht für Adminrechte)
    assert after.mfa is not None and after.mfa.status == "setup_required"
    assert _events(db, event_type="login.challenge", actor_user_id=user.id, outcome="success")


# ── Mails an die Person ─────────────────────────────────────────────────


def test_new_device_mail_once_per_device_and_failed_attempts_mail_deduplicated(db):
    tenant = make_tenant(db)
    user = make_app_user(db, email="mails@example.com", tenant_id=tenant.id)
    user.first_login_at = datetime.now(UTC) - timedelta(days=10)
    _known_device(db, user)  # Konto kennt schon ein Gerät
    _result, response = _login(db, user.email, ip="203.0.113.20")
    new_cookie = {name: value for name, value in _set_cookies(response).items() if "device" in name}
    _login(db, user.email, ip="203.0.113.20", cookies=new_cookie)
    kinds = [row.kind for row in db.scalars(select(Notification).where(Notification.recipient_id == user.id))]
    assert kinds.count("security.login_new_device") == 1
    for _ in range(settings.auth_account_failures_challenge + 3):
        try:
            _login(db, user.email, "falsch", ip=f"198.51.100.{_ % 9 + 1}", cookies=new_cookie)
        except HTTPException:
            pass
    kinds = [row.kind for row in db.scalars(select(Notification).where(Notification.recipient_id == user.id))]
    assert kinds.count("security.failed_attempts") == 1


def test_login_mails_render_in_all_languages_without_secrets():
    from app.core.locale_config_generated import SUPPORTED_LOCALES
    from app.notifications.render import render

    for lang in SUPPORTED_LOCALES:
        rendered = render(
            lang=lang, group="account.login_alert", recipient_name="Anna", tenant_name="Verein", base_url="https://app.example.com", can_login=True,
            items=[{"kind": "security.failed_attempts", "at": datetime.now(UTC), "device": "Firefox · Linux", "reasons": ["new_network"], "count": 31}],
        )
        assert "email." not in rendered.subject and "email.login" not in rendered.text
        assert "https://app.example.com/?profile=security" in rendered.text
        assert "https://app.example.com/?profile=notifications" in rendered.text
        notice = render(
            lang=lang, group="account.login_notice", recipient_name="Anna", tenant_name="Verein", base_url="https://app.example.com", can_login=True,
            items=[{"kind": "security.login_new_device", "at": datetime.now(UTC), "device": "Safari · iOS", "reasons": [], "count": 0}],
        )
        assert "Safari · iOS" in notice.text


# ── SEC-AUTH-011 Sessions (H1 invertiert, T8) ───────────────────────────


def test_H1_token_issued_before_revoke_in_the_same_second_is_invalid(db):
    user = make_app_user(db, email="same-second@example.com", tenant_id=make_tenant(db).id, role_code="writer")
    token = create_session_token(user.id)
    time.sleep(0.002)
    user.session_revoke_at = datetime.now(UTC)
    db.flush()
    assert get_optional_current_user(request=None, db=db, session_cookie=token) is None
    # ein danach ausgestelltes Token (Passwortwechsel: eigene Session bleibt) gilt
    assert get_optional_current_user(request=None, db=db, session_cookie=create_session_token(user.id)) is not None


def test_T8_single_session_revoke_and_idle_timeout(db):
    tenant = make_tenant(db)
    user = make_app_user(db, email="sessions@example.com", tenant_id=tenant.id, role_code="writer")
    _r1, first = _login(db, user.email, ip="203.0.113.30")
    _r2, second = _login(db, user.email, ip="203.0.113.31")
    token_a, token_b = _session_token(first), _session_token(second)
    sid_a = parse_session_token(token_a)["sid"]
    assert validate_session_token(db, token_a) and validate_session_token(db, token_b)
    sessions.revoke(db, [uuid.UUID(sid_a)], reason="test")
    db.commit()
    assert validate_session_token(db, token_a) is None
    assert validate_session_token(db, token_b) is not None
    # Inaktivität
    sid_b = uuid.UUID(parse_session_token(token_b)["sid"])
    db.execute(text("UPDATE auth_session SET last_seen_at = now() - make_interval(mins => :m) WHERE id = :id"), {"m": settings.auth_session_idle_minutes + 1, "id": sid_b})
    db.commit()
    db.expire_all()
    assert validate_session_token(db, token_b) is None
    assert db.get(AuthSession, sid_b).revoked_reason == "idle"


def test_tokens_from_before_the_update_stay_valid_until_they_expire(db):
    """Kein Zwangs-Logout beim Update: alte Tokens (ohne sid/kid/iat_ms) gelten weiter."""
    user = make_app_user(db, email="legacy-token@example.com", tenant_id=make_tenant(db).id, role_code="writer")
    now = int(time.time())
    payload = json.dumps({"user_id": user.id, "mfa": False, "iat": now, "exp": now + 3600}, separators=(",", ":")).encode()
    import hashlib
    import hmac as hmac_module

    signature = hmac_module.new(settings.auth_secret.encode(), payload, hashlib.sha256).digest()
    legacy = base64.urlsafe_b64encode(payload).decode() + "." + base64.urlsafe_b64encode(signature).decode()
    current = get_optional_current_user(request=None, db=db, session_cookie=legacy)
    assert current is not None and current.session_id is None


def test_previous_secret_still_verifies_tokens_during_rotation(db, monkeypatch):
    user = make_app_user(db, email="rotation@example.com", tenant_id=make_tenant(db).id, role_code="writer")
    old_token = create_session_token(user.id)
    monkeypatch.setattr(settings, "auth_secret_previous", settings.auth_secret)
    monkeypatch.setattr(settings, "auth_secret", secrets.token_hex(32))  # SECURITY-RULES 5.1: zur Laufzeit erzeugt
    assert get_optional_current_user(request=None, db=db, session_cookie=old_token) is not None
    monkeypatch.setattr(settings, "auth_secret_previous", "")
    assert get_optional_current_user(request=None, db=db, session_cookie=old_token) is None


def test_session_list_revoke_and_foreign_sessions(db):
    from app.api.routes import users as users_route

    tenant, other_tenant = make_tenant(db), make_tenant(db)
    user = make_app_user(db, email="devices@example.com", tenant_id=tenant.id, role_code="writer")
    other = make_app_user(db, email="other-devices@example.com", tenant_id=other_tenant.id, role_code="writer")
    _r, response = _login(db, user.email, ip="203.0.113.40")
    _r, _ = _login(db, user.email, ip="203.0.113.41")
    _r, other_response = _login(db, other.email, ip="203.0.113.42")
    current = get_optional_current_user(request=None, db=db, session_cookie=_session_token(response))
    listing = users_route.list_my_sessions(db=db, user=current)
    assert len(listing.sessions) == 2 and sum(item.current for item in listing.sessions) == 1
    # Fremde Session (anderer Mandant): 404, kein Existenz-Orakel
    other_sid = uuid.UUID(parse_session_token(_session_token(other_response))["sid"])
    other_public = db.get(AuthSession, other_sid).public_id
    with pytest.raises(HTTPException) as exc:
        users_route.revoke_my_session(other_public, Response(), db=db, user=current)
    assert exc.value.status_code == 404
    revoked = users_route.revoke_my_other_sessions(Response(), db=db, user=current)
    assert revoked["revoked"] == 1
    db.expire_all()
    assert len(users_route.list_my_sessions(db=db, user=current).sessions) == 1


def test_auth_session_rows_are_tenant_isolated(db):
    from tests.test_tenant_rls import as_app

    tenant_a, tenant_b = make_tenant(db), make_tenant(db)
    user_a = make_app_user(db, email="rls-a@example.com", tenant_id=tenant_a.id)
    user_b = make_app_user(db, email="rls-b@example.com", tenant_id=tenant_b.id)
    session_a = sessions.create(db, user_id=user_a.id, tenant_id=tenant_a.id, mfa=False, amr=["pwd"])
    session_b = sessions.create(db, user_id=user_b.id, tenant_id=tenant_b.id, mfa=False, amr=["pwd"])
    ids = [session_a.id, session_b.id]
    with as_app(db, tenant_a.id):
        assert set(db.scalars(select(AuthSession.id).where(AuthSession.id.in_(ids)))) == {session_a.id}


def test_logout_ends_only_this_device_and_logout_all_ends_every_device(db):
    tenant = make_tenant(db)
    user = make_app_user(db, email="logout@example.com", tenant_id=tenant.id, role_code="writer")
    _r, first = _login(db, user.email, ip="203.0.113.50")
    _r, second = _login(db, user.email, ip="203.0.113.51")
    token_a, token_b = _session_token(first), _session_token(second)
    current_a = get_optional_current_user(request=None, db=db, session_cookie=token_a)
    AuthService().logout(db, Response(), current_a)
    assert validate_session_token(db, token_a) is None and validate_session_token(db, token_b) is not None
    current_b = get_optional_current_user(request=None, db=db, session_cookie=token_b)
    AuthService().logout(db, Response(), current_b, everywhere=True)
    db.expire_all()
    assert validate_session_token(db, token_b) is None


# ── SEC-AUTH-010 Step-up (T17) ──────────────────────────────────────────


def test_T17_removing_a_factor_needs_a_fresh_step_up(db):
    from app.api.routes import users as users_route
    from app.schemas.step_up import StepUpRequest
    from app.services.step_up_service import StepUpService

    user, secret = make_mfa_enrolled_user(db, email="stepup@example.com", role_code="writer")
    db.add(UserMfaFactor(user_id=user.id, factor_type="totp", label="zweite", secret_encrypted=encrypt_secret(generate_totp_secret()), totp_last_counter=0))
    db.flush()
    factor = db.scalars(select(UserMfaFactor).where(UserMfaFactor.user_id == user.id)).first()
    record = sessions.create(db, user_id=user.id, tenant_id=user.tenant_id, mfa=True, amr=["pwd", "totp"])
    record.auth_time = datetime.now(UTC) - timedelta(hours=2)
    db.flush()
    current = build_current_user(db, user)
    current.mfa_verified = True
    current.session_id = record.id
    current.auth_time = record.auth_time
    with pytest.raises(HTTPException) as exc:
        users_route.delete_my_mfa_factor(factor.public_id, _req(), Response(), db=db, user=current)
    assert exc.value.status_code == 403 and exc.value.detail["code"] == "step_up_required"
    result = StepUpService().verify(db, Response(), current, StepUpRequest(method="totp", code=current_totp_code(secret)), request_host=None)
    current.auth_time = result.auth_time
    users_route.delete_my_mfa_factor(factor.public_id, _req(), Response(), db=db, user=current)
    assert _events(db, event_type="stepup.success", actor_user_id=user.id)
    assert _events(db, event_type="mfa.remove", actor_user_id=user.id)


def test_step_up_with_password_only_for_accounts_without_factor(db):
    from app.schemas.step_up import StepUpRequest
    from app.services.step_up_service import StepUpService

    user = make_app_user(db, email="stepup-pw@example.com", tenant_id=make_tenant(db).id, role_code="admin")
    current = build_current_user(db, user)
    with pytest.raises(HTTPException) as exc:
        StepUpService().verify(db, Response(), current, StepUpRequest(method="password", password="falsch"), request_host=None)
    assert exc.value.status_code == 401
    response = Response()
    StepUpService().verify(db, response, current, StepUpRequest(method="password", password=PASSWORD), request_host=None)
    # Session ohne Register (alt) wird übernommen: neues Cookie mit sid
    assert parse_session_token(_session_token(response)).get("sid")


def test_role_change_of_other_member_needs_step_up(db):
    from app.schemas.user import UserUpdate
    from app.services import role_service
    from app.services.user_service import UserService

    tenant = make_tenant(db)
    admin = make_app_user(db, email="roles-admin@example.com", tenant_id=tenant.id, role_code="admin")
    member = make_app_user(db, email="roles-member@example.com", tenant_id=tenant.id, role_code="reader")
    actor = build_current_user(db, admin)
    actor.auth_time = datetime.now(UTC) - timedelta(hours=1)
    writer = role_service.system_role(db, tenant.id, "writer")
    with pytest.raises(HTTPException) as exc:
        UserService().update_user(db, member.id, UserUpdate(role_ids=[writer.public_id]), actor)
    assert exc.value.detail["code"] == "step_up_required"
    # Name ändern braucht keine frische Anmeldung
    UserService().update_user(db, member.id, UserUpdate(display_name="Neuer Name"), actor)
    actor.auth_time = datetime.now(UTC)
    UserService().update_user(db, member.id, UserUpdate(role_ids=[writer.public_id]), actor)


# ── SEC-AUTH-014 (G1 invertiert), -015, -016 ────────────────────────────


def test_G1_websocket_auth_rejects_members_who_left(db):
    from app.api.routes.collaboration_ws import _authenticate_in
    from app.services.todo_fine_service import today

    user = make_app_user(db, email="left-ws@example.com", tenant_id=make_tenant(db).id, role_code="writer")
    token = create_session_token(user.id)
    assert _authenticate_in(db, token) is not None
    user.left_at = today() - timedelta(days=2)
    db.flush()
    assert _authenticate_in(db, token) is None


def test_left_member_with_correct_password_gets_generic_401(db):
    from app.services.todo_fine_service import today

    user = make_app_user(db, email="left-login@example.com", tenant_id=make_tenant(db).id, role_code="writer")
    user.left_at = today() - timedelta(days=1)
    db.flush()
    with pytest.raises(HTTPException) as exc:
        _login(db, user.email)
    assert exc.value.status_code == 401 and exc.value.detail["code"] == "invalid_credentials"


def test_password_rule_applies_to_self_service_change(db):
    from app.schemas.user import UserPasswordChange
    from app.services.user_service import UserService

    user = make_app_user(db, email="pw-rule@example.com", tenant_id=make_tenant(db).id, role_code="writer")
    current = build_current_user(db, user)
    with pytest.raises(HTTPException) as exc:
        UserService().change_own_password(db, current, UserPasswordChange(current_password=PASSWORD, new_password="Passwort" + str(123456 + time.time_ns() % 7)))
    assert exc.value.detail["code"] == "password_weak"


def test_password_reset_sends_at_most_three_mails_per_hour_and_never_429s_the_owner(db, monkeypatch):
    """Security-Review M6: je Adresse höchstens 3 Mails/h tatsächlich, darüber 202 ohne Versand;
    429 nur für die anfragende Quelle (> 10 in 15 min)."""
    from app.api.routes import auth as auth_route
    from app.main import app

    issued: list[str] = []
    monkeypatch.setattr(auth_route, "_email_sending_enabled", lambda _db: True)
    monkeypatch.setattr(auth_route, "_issue_password_reset", lambda email: issued.append(email))
    app.dependency_overrides[get_db] = lambda: db
    try:
        sources = [TestClient(app, base_url="https://hocx.example", raise_server_exceptions=False, client=(f"198.51.100.{n}", 40000)) for n in range(1, 5)]
        owner = TestClient(app, base_url="https://hocx.example", raise_server_exceptions=False, client=("203.0.113.9", 40000))
        for client in sources:
            for _ in range(4):
                assert client.post("/api/auth/password-reset/request", json={"email": "opfer@example.com"}).status_code == 202
        assert owner.post("/api/auth/password-reset/request", json={"email": "opfer@example.com"}).status_code == 202
        assert len(issued) == 3
        for _ in range(7):
            sources[0].post("/api/auth/password-reset/request", json={"email": "andere@example.com"})
        assert sources[0].post("/api/auth/password-reset/request", json={"email": "x@example.com"}).status_code == 429
    finally:
        app.dependency_overrides.pop(get_db, None)


class _SameSession:
    """SessionLocal-Ersatz für die Hintergrundaufgabe: dieselbe Test-Session, nicht schliessen."""

    def __init__(self, db) -> None:
        self.db = db

    def __call__(self):
        return self

    def __enter__(self):
        return self.db

    def __exit__(self, *_exc) -> None:
        return None


def test_password_reset_known_device_has_its_own_quota(db, monkeypatch):
    """Fremde verbrauchen das Adress-Kontingent; die Inhaberin kommt von einem bekannten Gerät
    ihres Kontos trotzdem durch (3/h je Gerät). Ohne, mit gefälschtem oder mit dem Gerätecookie
    eines anderen Kontos gibt es kein Zusatzkontingent - die Antwort ist immer 202."""
    from app.api.routes import auth as auth_route
    from app.main import app
    from app.notifications import account

    tenant = make_tenant(db)
    owner_user = make_app_user(db, email="geraet-opfer@example.com", tenant_id=tenant.id, role_code="writer")
    other_user = make_app_user(db, email="geraet-andere@example.com", tenant_id=tenant.id, role_code="writer")
    own_device = _known_device(db, owner_user)
    foreign_device = _known_device(db, other_user)
    name = devices.cookie_name()
    forged = {name: own_device[name][:-4] + "AAAA"}

    general: list[str] = []
    via_device: list[str] = []
    monkeypatch.setattr(auth_route, "_email_sending_enabled", lambda _db: True)
    monkeypatch.setattr(auth_route, "_issue_password_reset", lambda email: general.append(email))
    monkeypatch.setattr(auth_route, "SessionLocal", _SameSession(db))
    monkeypatch.setattr(account, "request_password_reset", lambda _db, email: via_device.append(email))
    app.dependency_overrides[get_db] = lambda: db

    def post(client, cookies=None):
        headers = {"cookie": "; ".join(f"{k}={v}" for k, v in cookies.items())} if cookies else {}
        response = client.post("/api/auth/password-reset/request", json={"email": owner_user.email}, headers=headers)
        assert response.status_code == 202 and response.json() == {"status": "accepted"}

    try:
        strangers = [TestClient(app, base_url="https://hocx.example", raise_server_exceptions=False, client=(f"198.51.100.{n}", 40000)) for n in range(1, 3)]
        owner = TestClient(app, base_url="https://hocx.example", raise_server_exceptions=False, client=("203.0.113.9", 40000))
        for client in strangers:
            for _ in range(3):
                post(client)
        assert len(general) == 3 and via_device == []  # Kontingent der Adresse aufgebraucht

        post(owner)  # ohne Gerätecookie: nichts
        post(owner, forged)  # gefälschte Signatur: nichts
        post(owner, foreign_device)  # Gerät eines anderen Kontos: nichts
        assert len(general) == 3 and via_device == []

        # Frische Quelle: nur das Adress-Kontingent ist erschöpft
        owner_fresh = TestClient(app, base_url="https://hocx.example", raise_server_exceptions=False, client=("203.0.113.10", 40000))
        for _ in range(4):
            post(owner_fresh, own_device)  # bekanntes Gerät: eigenes Kontingent, 3 pro Stunde
        assert via_device == [owner_user.email] * 3
        assert len(general) == 3

        # Widerrufenes Gerät bekommt nichts; ein zweites bekanntes Gerät wieder 3, danach Dach je Konto (6)
        revoked = _known_device(db, owner_user)
        devices.known_device(db, owner_user.id, devices.parse_cookie(revoked[name])).revoked_at = datetime.now(UTC)
        db.flush()
        post(owner_fresh, revoked)
        assert len(via_device) == 3
        second, third = _known_device(db, owner_user), _known_device(db, owner_user)
        for _ in range(3):
            post(owner_fresh, second)
        assert len(via_device) == 6
        post(owner_fresh, third)
        assert len(via_device) == 6
    finally:
        app.dependency_overrides.pop(get_db, None)


# ── SEC-AUTH-012 Telemetrie (T18) und Mandanten-Daten (T13) ─────────────

# Keine Codes (6 Ziffern), keine E-Mails, keine Tokens/Tickets (lange Base64url-Folgen)
_SECRET_PATTERN = re.compile(r"(\b\d{6}\b|@|[A-Za-z0-9_-]{30,})")


def test_T18_each_phase_writes_one_event_with_required_fields_and_no_secrets(db):
    user, secret = make_mfa_enrolled_user(db, email="telemetry@example.com", role_code="writer")
    with pytest.raises(HTTPException):
        _login(db, user.email, "falsch-passwort")
    result, _ = _login(db, user.email)
    with pytest.raises(HTTPException):
        AuthService().verify_login_totp(db, Response(), TotpLoginVerifyRequest(ticket=result.mfa.ticket, code="000000" if current_totp_code(secret) != "000000" else "111111"))
    AuthService().verify_login_totp(db, Response(), TotpLoginVerifyRequest(ticket=result.mfa.ticket, code=current_totp_code(secret)))
    rows = _events(db, actor_user_id=user.id)
    phases = [(row.event_type, row.outcome) for row in rows]
    for expected in [("login.password", "failure"), ("login.password", "success"), ("login.mfa.totp", "failure"), ("login.mfa.totp", "success"), ("login.success", "success")]:
        assert phases.count(expected) == 1, (expected, phases)
    for row in rows:
        assert row.event_id and row.ts and row.event_type in events.EVENT_TYPES and row.tenant_id == user.tenant_id
        assert not _SECRET_PATTERN.search(json.dumps(row.details)), row.details
        assert row.subject_hash is None or len(row.subject_hash) == 32
    success = [row for row in rows if row.event_type == "login.success"][0]
    assert success.session_id and success.device_hash and success.policy_version


def test_T13_cross_tenant_pattern_alarms_without_mixing_tenant_data(db):
    from app.auth_security import read_service

    tenants = [make_tenant(db) for _ in range(3)]
    users = [make_app_user(db, email=f"cross-{index}@example.com", tenant_id=tenant.id) for index, tenant in enumerate(tenants)]
    for user in users:
        with pytest.raises(HTTPException):
            _login(db, user.email, "falsch", ip="192.0.2.123")
    # Ereignisse aus dem Login haben ohne Request keine Quelle - für die Regel setzen
    db.execute(text("UPDATE auth_event SET src_net_hash = 'gemeinsames-netz' WHERE actor_user_id = ANY(:ids)"), {"ids": [user.id for user in users]})
    db.commit()
    assert any(threat.rule == "cross_tenant" for threat in threats.detect(db))
    own = read_service.tenant_events(db, tenants[0].id)
    assert own and all(event["user_id"] in (users[0].public_id, None) for event in own)
    assert all("src_net_hash" not in event and "subject_hash" not in event for event in own)


def test_tenant_activity_route_needs_access_manage(db):
    from app.api.routes import auth_security as route

    tenant = make_tenant(db)
    reader = make_app_user(db, email="activity-reader@example.com", tenant_id=tenant.id, role_code="reader")
    admin = make_app_user(db, email="activity-admin@example.com", tenant_id=tenant.id, role_code="admin")
    with pytest.raises(HTTPException) as exc:
        route.tenant_login_activity(limit=10, db=db, user=build_current_user(db, reader))
    assert exc.value.status_code == 403
    data = route.tenant_login_activity(limit=10, db=db, user=build_current_user(db, admin))
    assert {account["display_name"] for account in data["accounts"]} >= {reader.display_name, admin.display_name}


# ── Resilienz (T15) ─────────────────────────────────────────────────────


def test_T15_redis_down_known_device_logs_in_unknown_device_gets_503(db, monkeypatch):
    tenant = make_tenant(db)
    user = make_app_user(db, email="redis-down@example.com", tenant_id=tenant.id, role_code="writer")
    cookies = _known_device(db, user)

    class Down:
        def __getattr__(self, _name):
            def fail(*_args, **_kwargs):
                raise redis_sync.exceptions.ConnectionError("Redis weg")
            return fail

    for module in ("app.core.rate_limit", "app.auth_security.guard", "app.auth_security.blocks", "app.services.domain_bridge_service"):
        monkeypatch.setattr(f"{module}.get_redis_sync", lambda: Down())
    monkeypatch.setattr(rate_limit, "_script", lambda *_a: (_ for _ in ()).throw(redis_sync.exceptions.ConnectionError("Redis weg")))
    started = time.monotonic()
    with pytest.raises(HTTPException) as exc:
        _login(db, user.email, ip="203.0.113.60")
    assert exc.value.status_code == 503 and exc.value.detail["code"] == "auth_temporarily_unavailable"
    result, _ = _login(db, user.email, ip="203.0.113.61", cookies=cookies)
    assert result.authenticated
    assert time.monotonic() - started < 3


# ── T9 Single-Use-Races ─────────────────────────────────────────────────


def _committed_parent_session(user_id: int, *, auth_age_hours: float = 0) -> AuthSession:
    with SessionLocal() as session:
        user = session.get(AppUser, user_id)
        record = sessions.create(session, user_id=user_id, tenant_id=user.tenant_id, mfa=False, amr=["pwd"],
                                 expires_at=datetime.now(UTC) + timedelta(hours=5))
        record.auth_time = datetime.now(UTC) - timedelta(hours=auth_age_hours)
        session.commit()
        session.refresh(record)
        session.expunge(record)
        return record


def test_T9_bridge_token_redeems_exactly_once_in_parallel():
    from app.services import domain_bridge_service

    user_id = _committed_user(f"bridge-race-{uuid.uuid4().hex[:8]}@example.com")
    parent = _committed_parent_session(user_id)
    token = domain_bridge_service.create_bridge_token(user_id, "verein.example", mfa_verified=False, parent_sid=str(parent.id))
    # SEC-AUTH-020: dasselbe Token für dieselbe Session statt eines neuen je Abruf
    assert domain_bridge_service.create_bridge_token(user_id, "verein.example", mfa_verified=False, parent_sid=str(parent.id)) == token
    barrier = threading.Barrier(8)

    def redeem(_index: int) -> bool:
        with SessionLocal() as session:
            barrier.wait()
            return AuthService().redeem_bridge_token(session, Response(), token, "verein.example")

    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(redeem, range(8)))
    assert results.count(True) == 1


def test_admin_principal_uses_its_own_factor_counter():
    """Gemeinsame Primitive für den Plattform-Login (Admin-Branch): Admin-ID 1 und Konto-ID 1
    teilen sich keinen Zähler."""
    from app.auth_security.guard import consume_factor_attempt

    for _ in range(settings.auth_totp_account_limit):
        consume_factor_attempt(1, kind="totp", principal="admin")
    consume_factor_attempt(1, kind="totp")  # Konto 1 unberührt


# ── Security-Review (Folgerunde) ────────────────────────────────────────


def test_H1_bridge_child_inherits_parent_and_ends_with_it(db):
    from app.services import domain_bridge_service

    user = make_app_user(db, email="bridge-child@example.com", tenant_id=make_tenant(db).id, role_code="writer")
    parent = sessions.create(db, user_id=user.id, tenant_id=user.tenant_id, mfa=False, amr=["pwd"], expires_at=datetime.now(UTC) + timedelta(hours=5))
    parent.auth_time = datetime.now(UTC) - timedelta(hours=3)
    db.flush()
    # Ohne Eltern-Session keine Kind-Session
    orphan = domain_bridge_service.create_bridge_token(user.id, "verein.example")
    assert AuthService().redeem_bridge_token(db, Response(), orphan, "verein.example") is False
    token = domain_bridge_service.create_bridge_token(user.id, "verein.example", parent_sid=str(parent.id))
    response = Response()
    assert AuthService().redeem_bridge_token(db, response, token, "verein.example")
    child_token = _session_token(response)
    child = db.get(AuthSession, uuid.UUID(parse_session_token(child_token)["sid"]))
    assert child.parent_id == parent.id and child.expires_at == parent.expires_at and child.auth_time == parent.auth_time
    # Step-up gilt nicht als frisch, nur weil die Domain gewechselt wurde
    current = get_optional_current_user(request=None, db=db, session_cookie=child_token)
    from app.auth_security.step_up import is_recent

    assert not is_recent(current, settings.auth_step_up_admin_minutes)
    sessions.revoke(db, [parent.id], reason="test")
    db.commit()
    db.expire_all()
    assert validate_session_token(db, child_token) is None


def test_H1_session_poll_bridges_only_registered_sessions(db, monkeypatch):
    from app.services import domain_bridge_service

    calls = []
    monkeypatch.setattr(domain_bridge_service, "resolve_bridge_redirect", lambda *args, **kwargs: calls.append(kwargs) or None)
    from app.api.routes import auth as auth_route

    user = make_app_user(db, email="poll@example.com", tenant_id=make_tenant(db).id, role_code="writer")
    legacy = get_optional_current_user(request=None, db=db, session_cookie=create_session_token(user.id))
    auth_route.session(_req(), Response(), db=db, user=legacy)
    assert calls == []
    _r, response = _login(db, user.email)
    registered = get_optional_current_user(request=None, db=db, session_cookie=_session_token(response))
    auth_route.session(_req(), Response(), db=db, user=registered)
    assert calls and calls[-1]["parent_sid"] == str(registered.session_id)


def test_M1_legacy_session_is_adopted_without_getting_fresher_or_longer(db):
    from app.api.routes import users as users_route

    user = make_app_user(db, email="legacy-adopt@example.com", tenant_id=make_tenant(db).id, role_code="writer")
    now = int(time.time())
    payload = json.dumps({"user_id": user.id, "mfa": False, "iat": now - 7200, "exp": now + 3600}, separators=(",", ":")).encode()
    import hashlib
    import hmac as hmac_module

    signature = hmac_module.new(settings.auth_secret.encode(), payload, hashlib.sha256).digest()
    legacy = base64.urlsafe_b64encode(payload).decode() + "." + base64.urlsafe_b64encode(signature).decode()
    current = get_optional_current_user(request=None, db=db, session_cookie=legacy)
    response = Response()
    users_route.revoke_my_other_sessions(response, db=db, user=current)
    new_token = _session_token(response)
    data = parse_session_token(new_token)
    assert data["sid"] and data["exp"] <= now + 3600 + 1
    record = db.get(AuthSession, uuid.UUID(data["sid"]))
    assert record.auth_time <= datetime.now(UTC) - timedelta(minutes=100)


def test_M2_attack_mode_without_smtp_does_not_lock_out_unknown_devices(db, monkeypatch):
    from app.auth_security import guard

    monkeypatch.setattr(guard, "attack_mode", lambda _count: True)
    tenant = make_tenant(db)
    plain = make_app_user(db, email="attack-plain@example.com", tenant_id=tenant.id, role_code="writer")
    result, _ = _login(db, plain.email, ip="203.0.113.70")
    assert result.authenticated
    with_factor, _secret = make_mfa_enrolled_user(db, email="attack-mfa@example.com", tenant_id=tenant.id, role_code="writer")
    result, _ = _login(db, with_factor.email, ip="203.0.113.71")
    assert result.mfa is not None and result.mfa.status == "verification_required"


def test_M3_over_the_account_limit_unknown_devices_need_a_code_not_a_429(db, mail, monkeypatch):
    monkeypatch.setattr(settings, "auth_account_failures_known_only", 3)
    monkeypatch.setattr(settings, "auth_account_failures_challenge", 3)
    user = make_app_user(db, email="over-limit@example.com", tenant_id=make_tenant(db).id, role_code="writer")
    for index in range(5):
        with pytest.raises(HTTPException):
            _login(db, user.email, "falsch", ip=f"198.51.{index}.1")
    result, _ = _login(db, user.email, ip="203.0.113.80")
    assert result.mfa is not None and result.mfa.status == "email_verification_required"


def test_M3_without_smtp_over_limit_answers_uniformly(db, monkeypatch):
    monkeypatch.setattr(settings, "auth_account_failures_known_only", 3)
    user = make_app_user(db, email="over-limit-nosmtp@example.com", tenant_id=make_tenant(db).id, role_code="writer")
    for index in range(4):
        with pytest.raises(HTTPException):
            _login(db, user.email, "falsch", ip=f"198.51.{index}.2")
    codes = []
    for password in ("falsch", PASSWORD):
        with pytest.raises(HTTPException) as exc:
            _login(db, user.email, password, ip="203.0.113.81")
        codes.append((exc.value.status_code, exc.value.detail["code"]))
    assert codes[0] == codes[1] == (429, "login_denied")


def test_M3_password_reset_marks_the_device_as_known(db):
    from app.api.routes import auth as auth_route
    from app.notifications import account
    from app.schemas.notifications import AccountLinkComplete

    user = make_app_user(db, email="reset-device@example.com", tenant_id=make_tenant(db).id, role_code="writer")
    token_row = account._issue(db, user, "password_reset", created_by_user_id=None)
    raw = "reset-" + uuid.uuid4().hex + uuid.uuid4().hex
    token_row.token_hash = account.hash_token(raw)
    token_row.expires_at = datetime.now(UTC) + timedelta(minutes=30)
    db.flush()
    response = Response()
    auth_route.account_link_complete(AccountLinkComplete(token=raw, password="Fluss Ufer Möwe 42 x"), _req(), response, db=db)
    cookie = {name: value for name, value in _set_cookies(response).items() if "device" in name}
    assert devices.known_device(db, user.id, devices.parse_cookie(next(iter(cookie.values())))) is not None


def test_M4_foreign_device_id_is_never_bound_to_another_account(db):
    tenant = make_tenant(db)
    first = make_app_user(db, email="device-a@example.com", tenant_id=tenant.id, role_code="writer")
    second = make_app_user(db, email="device-b@example.com", tenant_id=tenant.id, role_code="writer")
    cookies = _known_device(db, first)
    _result, response = _login(db, second.email, cookies=cookies)
    issued = {name: value for name, value in _set_cookies(response).items() if "device" in name}
    assert issued and list(issued.values())[0] != list(cookies.values())[0]
    # Ohne Präfix wird das Cookie im Secure-Modus nicht gelesen
    unprefixed = {settings.auth_device_cookie: list(cookies.values())[0]}
    assert devices.device_id_from_request(_req(unprefixed)) is None


def test_M4_known_device_loses_its_exemption_after_failures(db):
    from app.auth_security.guard import count_device_failure

    user = make_app_user(db, email="device-guess@example.com", tenant_id=make_tenant(db).id, role_code="writer")
    cookies = _known_device(db, user)
    device_hash = devices.device_hash(devices.parse_cookie(list(cookies.values())[0]))
    for _ in range(settings.auth_account_ip_failures):
        count_device_failure(device_hash)
    events_before = len(_events(db, actor_user_id=user.id))
    _login(db, user.email, cookies=cookies)
    phase = [row for row in _events(db, actor_user_id=user.id)[events_before:] if row.event_type == "login.password" and row.outcome == "success"]
    assert phase and "new_device" in phase[-1].risk_reasons


def test_M5_ipv6_counts_and_blocks_per_48():
    a, b = source_address("2001:db8:7:1::1"), source_address("2001:db8:7:ffff::1")
    assert a.exact != b.exact and a.net == b.net == "2001:db8:7::/48" and a.wide == "2001:db8::/32"
    assert blocks.subject_for("2001:db8:7:1::1", "net") == blocks.subject_for("2001:db8:7:ffff::1", "net")


def test_N1_no_clear_ip_in_any_redis_key(db):
    with pytest.raises(HTTPException):
        _login(db, "jemand@example.com", "x", ip="198.51.100.123")
    for key in get_redis_sync().scan_iter("*"):
        assert "198.51.100" not in key and "jemand" not in key


def test_N2_legacy_cookie_name_only_during_transition(monkeypatch):
    from app.core import security

    monkeypatch.setattr(settings, "auth_legacy_cookie_until", "2000-01-01T00:00:00+00:00")
    assert settings.auth_session_cookie not in security.session_cookie_names()
    monkeypatch.setattr(settings, "auth_legacy_cookie_until", "2999-01-01T00:00:00+00:00")
    assert settings.auth_session_cookie in security.session_cookie_names()


def test_N5_step_up_does_not_extend_a_legacy_session(db):
    from app.schemas.step_up import StepUpRequest
    from app.services.step_up_service import StepUpService

    user = make_app_user(db, email="stepup-legacy@example.com", tenant_id=make_tenant(db).id, role_code="writer")
    token = create_session_token(user.id)
    current = get_optional_current_user(request=None, db=db, session_cookie=token)
    response = Response()
    StepUpService().verify(db, response, current, StepUpRequest(method="password", password=PASSWORD), request_host=None)
    assert parse_session_token(_session_token(response))["exp"] <= parse_session_token(token)["exp"] + 1
