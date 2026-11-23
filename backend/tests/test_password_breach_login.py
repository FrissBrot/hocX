"""Leak-Prüfung bestehender Passwörter beim Login (1.5.2, app/auth_security/breach.py).

HIBP wird nie angefragt: ``password_leak.check_password`` ist gemockt (die Prüfung selbst, Cache und
Abfragegrenze testet tests/test_password_leak.py). Geprüft wird der Ablauf: Markierung, zweiter
Faktor bzw. E-Mail-Code, genau eine Warn-Mail, Ausfall (fail-open), Aufheben nach Änderung,
Nachtjob und Plattform-Admins.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException, Response
from sqlalchemy import select, text
from starlette.requests import Request

from app.auth_security import breach
from app.core import password_leak, rate_limit
from app.core.redis_client import get_redis_sync
from app.core.security import build_current_user, hash_password
from app.models import Notification, PlatformAdmin
from app.notifications import email_transport
from app.schemas.admin import AdminLoginRequest
from app.schemas.user import LoginRequest
from app.services.admin_auth_service import AdminAuthService
from app.services.admin_mfa_service import AdminMfaService
from app.services.auth_service import AuthService
from app.services.notification_settings_service import NotificationSettingsService
from tests.factories import make_app_user, make_mfa_enrolled_user, make_tenant

PASSWORD = "correct horse battery staple"


def _flush() -> None:
    client = get_redis_sync()
    for pattern in ("ratelimit:*", "authsec:*", "authblock:*", "mfa:flow:*"):
        for key in client.scan_iter(pattern):
            client.delete(key)
    rate_limit.local_window.clear()


@pytest.fixture(autouse=True)
def _clean():
    _flush()
    yield
    _flush()


@pytest.fixture
def hibp(monkeypatch):
    """Gemockte Leak-Prüfung: ``state["leaked"]`` bzw. ``state["down"]`` steuern das Ergebnis,
    ``state["calls"]`` merkt sich ``fresh`` je Aufruf (nie das Passwort)."""
    state = {"leaked": False, "down": False, "calls": []}

    def fake(password: str, *, fresh: bool = False):
        state["calls"].append(fresh)
        if state["down"]:
            return password_leak.LeakResult(leaked=False, source="none")
        return password_leak.LeakResult(leaked=state["leaked"], source="hibp", count=7 if state["leaked"] else 0)

    monkeypatch.setattr(password_leak, "check_password", fake)
    return state


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


def _req() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/api/auth/login", "query_string": b"", "headers": []})


def _login(db, email: str, password: str = PASSWORD):
    return AuthService().login(db, Response(), LoginRequest(email=email, password=password), client_address="203.0.113.20", request=_req())


def _audits(db, action: str, *, user_id: int | None = None) -> int:
    sql = "SELECT count(*) FROM audit_log WHERE action = :action" + (" AND actor_user_id = :user_id" if user_id is not None else "")
    return int(db.scalar(text(sql), {"action": action, "user_id": user_id}))


def _warnings(db, user_id: int) -> int:
    return len(db.scalars(select(Notification).where(Notification.recipient_id == user_id, Notification.kind == "security.password_breached")).all())


def test_leaked_password_without_factor_requires_email_code_and_warns_once(db, mail, hibp):
    user = make_app_user(db, email="leak-ohne-faktor@example.com")
    hibp["leaked"] = True

    first = _login(db, user.email)
    assert first.authenticated is False
    assert first.mfa is not None and first.mfa.status == "email_verification_required"
    db.refresh(user)
    assert user.password_breached_at is not None and user.last_breach_check_at is not None
    assert _warnings(db, user.id) == 1
    assert _audits(db, "user.password_breached", user_id=user.id) == 1

    # Weitere Anmeldungen: wieder nur mit Code, aber keine zweite Warn-Mail und kein zweiter Audit-Eintrag
    second = _login(db, user.email)
    assert second.mfa is not None and second.mfa.status == "email_verification_required"
    assert _warnings(db, user.id) == 1
    assert _audits(db, "user.password_breached", user_id=user.id) == 1
    # Die App zeigt die Pflicht zur Änderung
    assert build_current_user(db, user).password_breached is True


def test_unleaked_password_logs_in_without_extra_step(db, mail, hibp):
    user = make_app_user(db, email="sauber@example.com")
    result = _login(db, user.email)
    assert result.authenticated is True and result.password_breached is False
    db.refresh(user)
    assert user.password_breached_at is None and user.last_breach_check_at is not None
    assert _warnings(db, user.id) == 0


def test_leaked_password_with_totp_requires_the_factor_not_a_mail_code(db, mail, hibp):
    user, _secret = make_mfa_enrolled_user(db, email="leak-mit-faktor@example.com")
    hibp["leaked"] = True
    result = _login(db, user.email)
    assert result.authenticated is False
    assert result.mfa is not None and result.mfa.status == "verification_required"
    assert _warnings(db, user.id) == 1


def test_leaked_password_without_factor_and_without_mail_is_refused(db, hibp):
    """Ohne Mailversand gibt es keinen zweiten Nachweis: keine Session mit dem geleakten Passwort."""
    user = make_app_user(db, email="leak-ohne-mail@example.com")
    hibp["leaked"] = True
    with pytest.raises(HTTPException) as refused:
        _login(db, user.email)
    assert refused.value.status_code == 503
    db.refresh(user)
    assert user.password_breached_at is not None


def test_hibp_outage_never_blocks_the_login(db, mail, hibp):
    user = make_app_user(db, email="hibp-weg@example.com")
    hibp["down"] = True
    result = _login(db, user.email)
    assert result.authenticated is True
    db.refresh(user)
    assert user.password_breached_at is None and user.last_breach_check_at is None


def test_unexpected_error_in_the_check_fails_open(db, mail, monkeypatch):
    user = make_app_user(db, email="pruefung-kaputt@example.com")

    def boom(password: str, *, fresh: bool = False):
        raise RuntimeError("kaputt")

    monkeypatch.setattr(password_leak, "check_password", boom)
    assert _login(db, user.email).authenticated is True


def test_wrong_password_is_never_checked_against_leaks(db, mail, hibp):
    user = make_app_user(db, email="falsch@example.com")
    with pytest.raises(HTTPException):
        _login(db, user.email, password="falsch-falsch-falsch")
    assert hibp["calls"] == []


def test_new_password_clears_the_mark(db, mail, hibp):
    user = make_app_user(db, email="aendern@example.com")
    hibp["leaked"] = True
    _login(db, user.email)
    db.refresh(user)
    assert user.password_breached_at is not None

    user.password_hash = hash_password("ein-neues-sicheres-passwort-" + user.email)
    db.flush()
    assert user.password_breached_at is None and user.breach_check_due_at is None
    assert build_current_user(db, user).password_breached is False
    hibp["leaked"] = False
    assert _login(db, user.email, password="ein-neues-sicheres-passwort-" + user.email).authenticated is True


def test_marks_are_per_account_never_across_tenants(db, mail, hibp):
    """Gleiches Passwort in einem anderen Verein: markiert wird nur das Konto, das sich anmeldet;
    die Markierung sieht nur dieses Konto selbst (eigene Session)."""
    tenant_a, tenant_b = make_tenant(db, "Verein A"), make_tenant(db, "Verein B")
    a = make_app_user(db, email="a@verein-a.example", tenant_id=tenant_a.id)
    b = make_app_user(db, email="b@verein-b.example", tenant_id=tenant_b.id)
    hibp["leaked"] = True
    _login(db, a.email)
    db.refresh(a)
    db.refresh(b)
    assert a.password_breached_at is not None
    assert b.password_breached_at is None
    assert _warnings(db, b.id) == 0
    assert build_current_user(db, b).password_breached is False


def test_nightly_job_marks_stale_checks_and_next_login_skips_the_cache(db, mail, hibp):
    stale = make_app_user(db, email="alt@example.com")
    fresh = make_app_user(db, email="frisch@example.com")
    never = make_app_user(db, email="nie@example.com")
    stale.last_breach_check_at = datetime.now(UTC) - timedelta(days=40)
    fresh.last_breach_check_at = datetime.now(UTC) - timedelta(days=2)
    db.flush()

    counts = breach.mark_due_accounts(db, older_than_days=30)
    assert counts["accounts"] >= 2
    for account in (stale, fresh, never):
        db.refresh(account)
    assert stale.breach_check_due_at is not None and never.breach_check_due_at is not None
    assert fresh.breach_check_due_at is None
    # Der Job liest keine Passwörter und prüft nichts selbst
    assert hibp["calls"] == []

    _login(db, stale.email)
    assert hibp["calls"] == [True]
    db.refresh(stale)
    assert stale.breach_check_due_at is None and stale.last_breach_check_at > datetime.now(UTC) - timedelta(minutes=5)
    _login(db, fresh.email)
    assert hibp["calls"] == [True, False]


def test_parallel_marking_sends_one_warning(db, mail, hibp):
    """Atomare Markierung: wer sie nicht setzt, schickt keine Mail."""
    user = make_app_user(db, email="parallel@example.com")
    hibp["leaked"] = True
    first = breach.check_on_login(db, user, PASSWORD)
    second = breach.check_on_login(db, user, PASSWORD)
    assert first.newly_marked is True and second.newly_marked is False and second.breached is True


def _admin(db, email: str) -> PlatformAdmin:
    admin = PlatformAdmin(email=email, password_hash=hash_password(PASSWORD), display_name="Admin", role="owner")
    db.add(admin)
    db.flush()
    return admin


def test_breached_admin_without_passkey_cannot_enroll_one(db, hibp):
    admin = _admin(db, "admin-leak@example.com")
    hibp["leaked"] = True
    with pytest.raises(HTTPException) as refused:
        AdminAuthService().login(db, Response(), AdminLoginRequest(email=admin.email, password=PASSWORD), client_address="203.0.113.30", request=_req())
    assert refused.value.status_code == 403 and refused.value.detail["code"] == "password_breached"
    db.refresh(admin)
    assert admin.password_breached_at is not None
    assert _audits(db, "admin.password_breached") >= 1


def test_breached_admin_with_passkey_still_needs_the_passkey(db, hibp, monkeypatch):
    admin = _admin(db, "admin-leak-passkey@example.com")
    monkeypatch.setattr(AdminMfaService, "has_passkey", lambda self, db_, admin_id: True)
    monkeypatch.setattr(AdminMfaService, "_list_passkeys", lambda self, db_, admin_id, for_update=False: [object()])
    hibp["leaked"] = True
    result = AdminAuthService().login(db, Response(), AdminLoginRequest(email=admin.email, password=PASSWORD), client_address="203.0.113.31", request=_req())
    assert result.authenticated is False and result.mfa is not None and result.mfa.status == "verification_required"
    db.refresh(admin)
    assert admin.password_breached_at is not None
    # Neues Passwort hebt die Markierung auch für Admins auf
    admin.password_hash = hash_password("neues-admin-passwort-lang")
    db.flush()
    assert admin.password_breached_at is None


def test_local_list_fallback_marks_hits_but_never_counts_as_a_full_check(db, mail, monkeypatch):
    """Security-Review 1.5.2: die lokale Liste (HIBP weg oder Abfragegrenze) kennt nur häufige
    Passwörter - ein Nicht-Treffer setzt weder Prüfzeitpunkt noch Fälligkeit zurück."""
    user = make_app_user(db, email="lokal@example.com")
    user.breach_check_due_at = datetime.now(UTC)
    db.flush()
    monkeypatch.setattr(password_leak, "check_password", lambda password, *, fresh=False: password_leak.LeakResult(leaked=False, source="local"))
    assert _login(db, user.email).authenticated is True
    db.refresh(user)
    assert user.last_breach_check_at is None and user.breach_check_due_at is not None
