"""Erstlogin über eine Einladung: Passwort → zweiter Faktor → angemeldet (ohne zweites Login).

Abläufe über HTTP (Router auth): Einladungslink einlösen (``/auth/account-link/complete``) liefert
nur ein Login-Ticket, nie eine Session; die Session entsteht erst mit bestätigtem Faktor bzw.
erlaubtem Überspringen (``/auth/mfa/setup/skip``). Pflicht kommt aus ``account_requires_mfa``.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.api.routes import auth
from app.core.config import settings
from app.core.db import get_db
from app.core.mfa_policy import account_requires_mfa
from app.core.redis_client import get_redis_sync
from app.core.security import hash_password, verify_password
from app.core.totp import current_totp_code
from app.models import AccountToken, UserMfaFactor
from app.notifications import account
from tests.factories import assign_roles, make_app_user, make_participant, make_tenant


def _strong_password() -> str:
    # Zur Laufzeit erzeugt (SECURITY-RULES 5.1); vier Zeichenarten, kein Name/Wort.
    # Nur Konsonanten ohne direkte Wiederholung: kann kein häufiges Wort, keinen Namen und kein
    # «aaa» enthalten, die Prüfung bleibt deterministisch.
    chars: list[str] = []
    while len(chars) < 10:
        char = secrets.choice("bcdfghjkmnpqrstvwxz")
        if not chars or chars[-1] != char:
            chars.append(char)
    return "Zq-" + "".join(chars) + "-7Vx"


@pytest.fixture
def club(db):
    tenant = make_tenant(db, "Musterverein Seeland")
    anna = make_app_user(db, "anna@example.com", tenant_id=tenant.id, first_name="Anna", last_name="A", role_code="admin")
    ben = make_participant(db, tenant.id, "Ben Beispiel")
    ben.first_name, ben.last_name, ben.email = "Ben", "Beispiel", "ben@beispiel.ch"
    db.flush()
    return {"tenant": tenant, "anna": anna, "ben": ben}


def _invite_token(db, club, user=None) -> str:
    """Einladung wie im Versand (link_items_for): nur der Hash liegt in der DB."""
    user = user or club["ben"]
    row = account.invite(db, user, actor_user_id=club["anna"].id)
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    row.token_hash, row.sent_at, row.expires_at = account.hash_token(token), now, now + account.TOKEN_TTL["invite"]
    db.flush()
    return token


def _client(db) -> TestClient:
    app = FastAPI()
    app.include_router(auth.router, prefix="/api/auth")
    app.dependency_overrides[get_db] = lambda: db
    # https: der Session-Cookie ist Secure und käme über http nie zurück
    return TestClient(app, base_url="https://testserver")


@pytest.fixture
def no_ip_limit(monkeypatch):
    monkeypatch.setattr(auth, "enforce_rate_limit", lambda *args, **kwargs: None)


def _session(client: TestClient) -> dict:
    return client.get("/api/auth/session").json()


# ── Ablauf ohne Pflicht ─────────────────────────────────────────────────


def test_invite_without_obligation_returns_ticket_but_no_session(db, club, no_ip_limit):
    client = _client(db)
    password = _strong_password()
    response = client.post("/api/auth/account-link/complete", json={"token": _invite_token(db, club), "password": password})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["purpose"] == "invite"
    assert body["mfa_required"] is False
    assert body["mfa"]["status"] == "setup_required" and body["mfa"]["can_skip"] is True and body["mfa"]["required"] is False
    assert settings.auth_session_cookie not in response.cookies
    assert _session(client)["authenticated"] is False
    ben = club["ben"]
    db.refresh(ben)
    assert ben.login_enabled and verify_password(password, ben.password_hash)


def test_skip_without_obligation_logs_in_directly(db, club, no_ip_limit):
    client = _client(db)
    body = client.post("/api/auth/account-link/complete", json={"token": _invite_token(db, club), "password": _strong_password()}).json()
    skipped = client.post("/api/auth/mfa/setup/skip", json={"ticket": body["mfa"]["ticket"]})
    assert skipped.status_code == 200, skipped.text
    assert skipped.json()["authenticated"] is True
    session = _session(client)
    assert session["authenticated"] is True and session["user"]["email"] == "ben@beispiel.ch"
    actions = set(db.scalars(text("SELECT action FROM audit_log WHERE actor_user_id = :id"), {"id": club["ben"].id}))
    assert {"user.invite_accepted", "user.mfa_setup_skipped", "user.login"} <= actions
    # Ticket ist verbraucht: kein zweites Mal
    assert client.post("/api/auth/mfa/setup/skip", json={"ticket": body["mfa"]["ticket"]}).status_code == 401


def test_totp_setup_after_invite_logs_in_with_verified_mfa(db, club, no_ip_limit):
    client = _client(db)
    body = client.post("/api/auth/account-link/complete", json={"token": _invite_token(db, club), "password": _strong_password()}).json()
    start = client.post("/api/auth/mfa/totp/setup/start", json={"ticket": body["mfa"]["ticket"]}).json()
    assert start["provisioning_uri"].startswith("otpauth://totp/")
    done = client.post("/api/auth/mfa/totp/setup/complete", json={"flow_token": start["flow_token"], "code": current_totp_code(start["secret"]), "label": "Handy"})
    assert done.status_code == 200, done.text
    assert _session(client)["authenticated"] is True
    factor = db.scalar(select(UserMfaFactor).where(UserMfaFactor.user_id == club["ben"].id))
    assert factor is not None and factor.label == "Handy"


# ── Ablauf mit Pflicht ──────────────────────────────────────────────────


def test_obligation_comes_from_the_single_policy_function(db, club):
    ben = club["ben"]
    assert account_requires_mfa(db, ben.id) is False
    assign_roles(db, ben, "admin")
    assert account_requires_mfa(db, ben.id) is True


def test_mandatory_mfa_blocks_skip_and_session_until_factor_confirmed(db, club, no_ip_limit):
    ben = club["ben"]
    assign_roles(db, ben, "admin")
    client = _client(db)
    response = client.post("/api/auth/account-link/complete", json={"token": _invite_token(db, club), "password": _strong_password()})
    body = response.json()
    assert body["mfa_required"] is True
    assert body["mfa"]["required"] is True and body["mfa"]["can_skip"] is False
    assert settings.auth_session_cookie not in response.cookies

    skipped = client.post("/api/auth/mfa/setup/skip", json={"ticket": body["mfa"]["ticket"]})
    assert skipped.status_code == 403
    assert skipped.json()["detail"]["code"] == "mfa_skip_not_allowed"
    assert _session(client)["authenticated"] is False

    start = client.post("/api/auth/mfa/totp/setup/start", json={"ticket": body["mfa"]["ticket"]}).json()
    wrong = client.post("/api/auth/mfa/totp/setup/complete", json={"flow_token": start["flow_token"], "code": "000000"})
    if wrong.status_code == 200:  # pragma: no cover - 1:10^6, dann ist der Code zufällig richtig
        pytest.skip("Zufällig gültiger Code")
    assert wrong.status_code == 400
    assert _session(client)["authenticated"] is False

    done = client.post("/api/auth/mfa/totp/setup/complete", json={"flow_token": start["flow_token"], "code": current_totp_code(start["secret"])})
    assert done.status_code == 200, done.text
    session = _session(client)
    assert session["authenticated"] is True


def test_skip_is_refused_for_a_normal_login_ticket(db, club, no_ip_limit):
    """Ein Ticket aus dem normalen Login (ohne Faktor gibt es das nur bei Pflicht) ist kein
    Einladungs-Ticket: Überspringen wird serverseitig abgelehnt."""
    password = _strong_password()
    admin = make_app_user(db, "chef@example.com", tenant_id=club["tenant"].id, role_code="admin")
    admin.password_hash = hash_password(password)
    db.flush()
    client = _client(db)
    pending = client.post("/api/auth/login", json={"email": "chef@example.com", "password": password}).json()
    assert pending["mfa"]["status"] == "setup_required" and pending["mfa"]["can_skip"] is False
    assert client.post("/api/auth/mfa/setup/skip", json={"ticket": pending["mfa"]["ticket"]}).status_code == 403
    assert client.post("/api/auth/mfa/setup/skip", json={"ticket": "erfunden"}).status_code == 401


def test_ticket_dies_when_sessions_are_revoked_afterwards(db, club, no_ip_limit):
    """Setzt ein Admin nach dem Einlösen alle Sessions zurück (Passwort-/MFA-Reset), gilt auch das
    Ticket nicht mehr (Security-Review: 30-Minuten-Fenster)."""
    client = _client(db)
    body = client.post("/api/auth/account-link/complete", json={"token": _invite_token(db, club), "password": _strong_password()}).json()
    ben = club["ben"]
    ben.session_revoke_at = datetime.now(timezone.utc) + timedelta(seconds=5)
    db.flush()
    skipped = client.post("/api/auth/mfa/setup/skip", json={"ticket": body["mfa"]["ticket"]})
    assert skipped.status_code == 401 and skipped.json()["detail"]["code"] == "mfa_flow_expired"
    assert client.post("/api/auth/mfa/totp/setup/start", json={"ticket": body["mfa"]["ticket"]}).status_code == 401


# ── Einmal-Token, ungültige Zustände ───────────────────────────────────


def test_invite_token_is_single_use(db, club, no_ip_limit):
    client = _client(db)
    token = _invite_token(db, club)
    assert client.post("/api/auth/account-link/complete", json={"token": token, "password": _strong_password()}).status_code == 200
    again = client.post("/api/auth/account-link/complete", json={"token": token, "password": _strong_password()})
    assert again.status_code == 400 and again.json()["detail"]["code"] == "link_invalid"
    assert client.post("/api/auth/account-link/preview", json={"token": token}).status_code == 404


def test_expired_revoked_and_unknown_links_answer_identically(db, club, no_ip_limit):
    client = _client(db)
    expired = _invite_token(db, club)
    row = db.scalar(select(AccountToken).where(AccountToken.token_hash == account.hash_token(expired)))
    row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.flush()
    other = make_participant(db, club["tenant"].id, "Cora C")
    other.email = "cora@example.com"
    db.flush()
    revoked = _invite_token(db, club, other)
    account.revoke_invite(db, other.id)

    previews = [client.post("/api/auth/account-link/preview", json={"token": token}) for token in (expired, revoked, "unbekannt")]
    assert {r.status_code for r in previews} == {404}
    assert len({r.text for r in previews}) == 1
    completes = [client.post("/api/auth/account-link/complete", json={"token": token, "password": _strong_password()}) for token in (expired, revoked, "unbekannt")]
    assert {r.status_code for r in completes} == {400}
    assert len({r.text for r in completes}) == 1
    assert not any(settings.auth_session_cookie in r.cookies for r in completes)


# ── Passwortregel (serverseitig, gleiche Regel wie die Anzeige) ─────────


@pytest.mark.parametrize("password", ["BenBeispiel-2026!", "ben@beispiel.ch-X1", "Seeland-Wald-77x", "Passwort-Sicher-9", "Aaa-bbbbb-cccc-1X", "kurz-Aa1!"])
def test_weak_passwords_are_rejected_and_keep_the_link(db, club, no_ip_limit, password):
    client = _client(db)
    token = _invite_token(db, club)
    response = client.post("/api/auth/account-link/complete", json={"token": token, "password": password})
    if len(password) < 12:
        assert response.status_code == 422
    else:
        assert response.status_code == 400 and response.json()["detail"]["code"] == "password_weak"
    row = db.scalar(select(AccountToken).where(AccountToken.token_hash == account.hash_token(token)))
    assert row.used_at is None
    assert client.post("/api/auth/account-link/complete", json={"token": token, "password": _strong_password()}).status_code == 200


def test_password_reset_uses_the_same_rule(db, club, no_ip_limit):
    anna = club["anna"]
    row = account._issue(db, anna, "password_reset", created_by_user_id=None)
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    row.token_hash, row.sent_at, row.expires_at = account.hash_token(token), now, now + timedelta(minutes=60)
    db.flush()
    client = _client(db)
    weak = client.post("/api/auth/account-link/complete", json={"token": token, "password": "anna-example-1234"})
    assert weak.status_code == 400 and weak.json()["detail"]["code"] == "password_weak"
    ok = client.post("/api/auth/account-link/complete", json={"token": token, "password": _strong_password()})
    assert ok.status_code == 200 and ok.json() == {"purpose": "password_reset", "mfa": None, "mfa_required": None}


# ── Rate-Limits ─────────────────────────────────────────────────────────


def test_public_invite_steps_are_rate_limited(db, club):
    redis = get_redis_sync()
    keys = ["ratelimit:account-link-ip:testclient", "ratelimit:mfa-setup-ip:testclient"]
    redis.delete(*keys)
    try:
        client = _client(db)
        statuses = [client.post("/api/auth/account-link/preview", json={"token": "unbekannt"}).status_code for _ in range(31)]
        assert statuses[:30] == [404] * 30 and statuses[30] == 429
        complete = client.post("/api/auth/account-link/complete", json={"token": "unbekannt", "password": _strong_password()})
        assert complete.status_code == 429 and complete.json()["detail"]["code"] == "rate_limited"
        skips = [client.post("/api/auth/mfa/setup/skip", json={"ticket": "erfunden"}).status_code for _ in range(201)]
        assert skips[:200] == [401] * 200 and skips[200] == 429
    finally:
        redis.delete(*keys)


# ── Einladungs-Mail im Design-Look ──────────────────────────────────────

INVITE_LINK = "https://app.example.com/auth/set-password#token=x&kind=invite"


def _render_invite(lang: str):
    from app.notifications.render import render_account

    item = {"kind": "account.invite", "link": INVITE_LINK, "valid_hours": 168, "valid_minutes": 10080}
    return render_account(
        lang=lang, group="account.invite", items=[item], recipient_name="Ben", tenant_name="Musterverein Seeland",
        base_url="https://app.example.com", can_login=False,
    )


def test_invite_mail_matches_the_design():
    mail = _render_invite("de")
    assert mail.subject == "Musterverein Seeland: Einladung zu hocX"
    assert "Willkommen bei hocX" in mail.html and "Hallo Ben" in mail.text
    assert f"Konto einrichten: {INVITE_LINK}" in mail.text
    assert "Der Link ist 7 Tage gültig und funktioniert nur einmal." in mail.text
    assert "Diese Nachricht kommt von Musterverein Seeland über hocX." in mail.text


def test_invite_mail_exists_in_every_language():
    from app.core.locale_config_generated import LOCALES

    subjects = {lang: _render_invite(lang).subject for lang in LOCALES}
    assert all("Musterverein Seeland" in subject and "hocX" in subject for subject in subjects.values())
    assert len(set(subjects.values())) == len(LOCALES)


# ── 3-Tage-Frist bei bestehenden Konten (Migration 0192) ────────────────


def _reader_login(db, club, email: str, *, existing: bool) -> tuple[TestClient, dict]:
    password = _strong_password()
    reader = make_app_user(db, email, tenant_id=club["tenant"].id, role_code="reader")
    reader.password_hash = hash_password(password)
    if existing:
        reader.first_login_at = datetime.now(timezone.utc) - timedelta(days=30)
    club["tenant"].require_mfa = True
    db.flush()
    client = _client(db)
    return client, client.post("/api/auth/login", json={"email": email, "password": password}).json()


def test_existing_account_in_grace_sees_setup_but_may_skip(db, club, no_ip_limit):
    client, pending = _reader_login(db, club, "leser@example.com", existing=True)
    assert pending["mfa"]["status"] == "setup_required" and pending["mfa"]["can_skip"] is True
    assert pending["mfa"]["grace_until"]
    skipped = client.post("/api/auth/mfa/setup/skip", json={"ticket": pending["mfa"]["ticket"]})
    assert skipped.status_code == 200, skipped.text
    session = _session(client)
    assert session["authenticated"] is True and session["mfa_grace_until"]


def test_new_account_must_set_up_without_skip(db, club, no_ip_limit):
    client, pending = _reader_login(db, club, "neu-leser@example.com", existing=False)
    assert pending["mfa"]["status"] == "setup_required" and pending["mfa"]["can_skip"] is False
    assert client.post("/api/auth/mfa/setup/skip", json={"ticket": pending["mfa"]["ticket"]}).status_code == 403
