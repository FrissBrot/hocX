"""Konto und Sicherheit (Benachrichtigungen Phase 3, app/notifications/account.py, Migration 0171)."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app.api.routes import auth, participants
from app.core.db import get_db
from app.core.security import get_current_user, verify_password
from app.models import AccountToken, Notification, TenantDataExport
from app.notifications import account, dispatch, email_transport, exports
from app.notifications import preferences as notification_preferences
from app.schemas.participant import ParticipantUpdate
from app.schemas.user import UserPasswordChange, UserUpdate
from app.services.participant_service import ParticipantService
from app.services.notification_settings_service import NotificationSettingsService
from app.services.user_service import UserService
from tests.factories import make_app_user, make_current_user, make_participant, make_tenant

PASSWORD = "ein-sehr-langes-passwort"


@pytest.fixture
def sent():
    mails: list = []
    email_transport.override_transport(lambda config, email: mails.append(email))
    yield mails
    email_transport.override_transport(None)


@pytest.fixture
def club(db):
    row = NotificationSettingsService().get_row(db)
    row.email_enabled = True
    row.smtp_host = "smtp.example.com"
    row.email_from_address = "noreply@example.com"
    row.email_link_base_url = "https://app.example.com"
    tenant = make_tenant(db, "Pfadi Konto")
    anna = make_app_user(db, "anna@example.com", tenant_id=tenant.id, first_name="Anna", last_name="A", role_code="admin")
    neu = make_participant(db, tenant.id, "Neu Person")
    neu.email = "neu@example.com"
    db.flush()
    return {"tenant": tenant, "anna": anna, "neu": neu}


def _deliver(db) -> None:
    """Fällig machen (now() steht in der Testtransaktion still) und den Loop laufen lassen."""
    db.execute(update(Notification).where(Notification.status == "pending").values(deliver_after=datetime.now(timezone.utc) - timedelta(hours=1)))
    db.flush()
    dispatch.run(db)


def _token_from(mail) -> str:
    match = re.search(r"/auth/set-password#token=([A-Za-z0-9_\-]+)", mail.text)
    assert match, mail.text
    return match.group(1)


def _tokens(db, user_id: int, purpose: str) -> list[AccountToken]:
    return list(db.scalars(select(AccountToken).where(AccountToken.user_id == user_id, AccountToken.purpose == purpose).order_by(AccountToken.id)))


def test_password_reset_sends_a_one_time_link_and_sets_the_password(db, club, sent):
    anna = club["anna"]
    account.request_password_reset(db, "  ANNA@example.com ")
    _deliver(db)

    assert [mail.to for mail in sent] == ["anna@example.com"]
    token = _token_from(sent[0])
    row = _tokens(db, anna.id, "password_reset")[0]
    # Nur der Hash liegt in der Datenbank, das Token steht nur in der Mail
    assert row.token_hash == account.hash_token(token) and token not in row.token_hash
    assert row.expires_at - row.sent_at == timedelta(minutes=60)
    assert account.preview(db, token)["purpose"] == "password_reset"

    before = datetime.now(timezone.utc) - timedelta(seconds=5)
    assert account.complete(db, token, PASSWORD) == "password_reset"
    db.refresh(anna)
    assert verify_password(PASSWORD, anna.password_hash)
    assert anna.session_revoke_at >= before
    with pytest.raises(HTTPException) as reused:
        account.complete(db, token, PASSWORD + "x")
    assert reused.value.status_code == 400
    # Sicherheitshinweis an die Person
    notice = db.scalars(select(Notification).where(Notification.recipient_id == anna.id, Notification.kind == "security.password_changed")).all()
    assert len(notice) == 1


def test_password_reset_does_nothing_for_unknown_inactive_or_login_less_accounts(db, club, sent):
    account.request_password_reset(db, "niemand@example.com")
    account.request_password_reset(db, "neu@example.com")  # ohne Login
    club["anna"].is_active = False
    db.flush()
    account.request_password_reset(db, "anna@example.com")
    assert db.scalars(select(AccountToken)).all() == []
    _deliver(db)
    assert sent == []


def test_a_new_request_revokes_the_older_link(db, club, sent):
    anna = club["anna"]
    account.request_password_reset(db, "anna@example.com")
    account.request_password_reset(db, "anna@example.com")
    _deliver(db)
    first, second = _tokens(db, anna.id, "password_reset")
    assert first.revoked_at is not None and first.token_hash is None
    assert len(sent) == 1 and account.hash_token(_token_from(sent[0])) == second.token_hash


def test_expired_link_is_rejected(db, club, sent):
    account.request_password_reset(db, "anna@example.com")
    _deliver(db)
    token = _token_from(sent[0])
    db.execute(update(AccountToken).values(expires_at=datetime.now(timezone.utc) - timedelta(minutes=1)))
    db.flush()
    assert account.preview(db, token) is None
    with pytest.raises(HTTPException):
        account.complete(db, token, PASSWORD)


def test_invite_reaches_person_without_login_and_enables_login_on_accept(db, club, sent):
    neu = club["neu"]
    account.invite(db, neu, actor_user_id=club["anna"].id)
    _deliver(db)

    assert [mail.to for mail in sent] == ["neu@example.com"]
    assert "Pfadi Konto" in sent[0].subject
    token = _token_from(sent[0])
    assert account.preview(db, token)["purpose"] == "invite"
    assert account.complete(db, token, PASSWORD) == "invite"
    db.refresh(neu)
    assert neu.login_enabled and verify_password(PASSWORD, neu.password_hash)
    assert _tokens(db, neu.id, "invite")[0].used_at is not None


def test_invite_fails_on_accept_when_the_email_got_taken(db, club, sent):
    neu = club["neu"]
    account.invite(db, neu, actor_user_id=club["anna"].id)
    _deliver(db)
    other_tenant = make_tenant(db, "Anderer Verein")
    make_app_user(db, "neu@example.com", tenant_id=other_tenant.id)
    with pytest.raises(HTTPException) as taken:
        account.complete(db, _token_from(sent[0]), PASSWORD)
    assert taken.value.status_code == 409


def test_revoked_invite_link_no_longer_works(db, club, sent):
    neu = club["neu"]
    account.invite(db, neu, actor_user_id=club["anna"].id)
    _deliver(db)
    account.revoke_invite(db, neu.id)
    assert account.preview(db, _token_from(sent[0])) is None


def test_security_notices_are_mandatory_and_sent(db, club, sent):
    anna = club["anna"]
    actor = make_current_user(club["tenant"].id, role="admin", user_id=anna.id)
    UserService().change_own_password(db, actor, UserPasswordChange(current_password="correct horse battery staple", new_password=PASSWORD))
    # Die Kategorie «account» steht nicht in den Einstellungen und lässt sich nicht abschalten
    categories = [p.category for p in notification_preferences.read(db, anna.id, club["tenant"].id).preferences]
    assert "account" not in categories and "exports" in categories
    assert dispatch.preference_enabled(db, anna.id, "account")
    _deliver(db)
    assert len(sent) == 1 and "Sicherheitshinweis" in sent[0].subject


def _berta(db, club):
    return make_app_user(db, "berta@example.com", tenant_id=club["tenant"].id, first_name="Berta", last_name="B", role_code="reader")


def test_login_email_change_notifies_the_old_address_without_links(db, club, sent):
    berta = _berta(db, club)
    actor = make_current_user(club["tenant"].id, role="admin", user_id=club["anna"].id)
    UserService().update_user(db, berta.id, UserUpdate(email=" Berta.Neu@example.com "), actor)
    _deliver(db)
    assert [mail.to for mail in sent] == ["berta@example.com"]
    mail = sent[0]
    assert "Login-E-Mail" in mail.subject and "Vereinsverwaltung" in mail.text
    # Reiner Hinweis: weder die neue Adresse noch ein Link oder Token
    assert "berta.neu@example.com" not in mail.text and "http" not in mail.text and "token" not in mail.text.lower()
    assert "http" not in mail.html.replace("<!doctype html>", "")


def test_login_email_change_via_participant_edit_notifies_the_old_address(db, club, sent):
    berta = _berta(db, club)
    ParticipantService().update_participant(db, berta.id, ParticipantUpdate(email="berta2@example.com"), tenant_id=club["tenant"].id)
    _deliver(db)
    assert [mail.to for mail in sent] == ["berta@example.com"]


def test_unchanged_login_email_sends_nothing(db, club, sent):
    berta = _berta(db, club)
    actor = make_current_user(club["tenant"].id, role="admin", user_id=club["anna"].id)
    UserService().update_user(db, berta.id, UserUpdate(email="BERTA@example.com", first_name="Berta"), actor)
    ParticipantService().update_participant(db, berta.id, ParticipantUpdate(email="berta@example.com"), tenant_id=club["tenant"].id)
    assert db.scalar(select(Notification).where(Notification.kind == "security.email_changed")) is None


def test_export_ready_notifies_the_requester(db, club, sent):
    anna = club["anna"]
    job = TenantDataExport(tenant_id=club["tenant"].id, requested_by=anna.id, status="done", filename="Export.zip")
    db.add(job)
    db.flush()
    exports.on_export_finished(db, job)
    exports.on_export_finished(db, job)  # einmalig
    _deliver(db)
    assert len(sent) == 1 and "Export.zip" in sent[0].text and "/tenant-settings/privacy" in sent[0].text


# ── HTTP ──────────────────────────────────────────────────────────────


def _client(db, actor=None) -> TestClient:
    app = FastAPI()
    app.include_router(auth.router, prefix="/api/auth")
    app.include_router(participants.router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    if actor is not None:
        app.dependency_overrides[get_current_user] = lambda: actor
    return TestClient(app)


def test_public_endpoints_answer_without_revealing_accounts(db, club, monkeypatch):
    issued: list[str] = []
    monkeypatch.setattr(auth, "_issue_password_reset", issued.append)
    monkeypatch.setattr(auth, "enforce_rate_limit", lambda *args, **kwargs: None)
    client = _client(db)
    assert client.get("/api/auth/password-reset/available").json() == {"enabled": True}
    known = client.post("/api/auth/password-reset/request", json={"email": "anna@example.com"})
    unknown = client.post("/api/auth/password-reset/request", json={"email": "niemand@example.com"})
    assert known.status_code == unknown.status_code == 202 and known.json() == unknown.json()
    assert client.post("/api/auth/account-link/preview", json={"token": "falsch"}).status_code == 404
    assert client.post("/api/auth/account-link/complete", json={"token": "falsch", "password": PASSWORD}).status_code == 400
    assert client.post("/api/auth/account-link/complete", json={"token": "falsch", "password": "kurz"}).status_code == 422


def test_invite_route_requires_access_manage_and_own_tenant(db, club, monkeypatch):
    monkeypatch.setattr(participants, "enforce_rate_limit", lambda *args, **kwargs: None)
    neu = club["neu"]
    writer = _client(db, make_current_user(club["tenant"].id, role="writer", user_id=club["anna"].id))
    assert writer.post(f"/api/participants/{neu.public_id}/invite").status_code == 403
    foreign = make_tenant(db, "Fremder Verein")
    stranger = make_app_user(db, "fremd@example.com", tenant_id=foreign.id, role_code="admin")
    other = _client(db, make_current_user(foreign.id, role="admin", user_id=stranger.id))
    assert other.post(f"/api/participants/{neu.public_id}/invite").status_code == 404

    admin = _client(db, make_current_user(club["tenant"].id, role="admin", user_id=club["anna"].id))
    created = admin.post(f"/api/participants/{neu.public_id}/invite")
    assert created.status_code == 201, created.text
    assert [row["participant_id"] for row in admin.get("/api/participants/invites").json()] == [str(neu.public_id)]
    assert admin.post(f"/api/participants/{club['anna'].public_id}/invite").status_code == 409  # hat schon Login
    assert admin.delete(f"/api/participants/{neu.public_id}/invite").status_code == 200
    assert admin.get("/api/participants/invites").json() == []


def test_changing_the_email_revokes_open_links(db, club, sent):
    from app.schemas.participant import ParticipantUpdate
    from app.services.participant_service import ParticipantService

    neu = club["neu"]
    account.invite(db, neu, actor_user_id=club["anna"].id)
    _deliver(db)
    ParticipantService().update_participant(db, neu.id, ParticipantUpdate(email="andere@example.com"), tenant_id=club["tenant"].id)
    assert account.preview(db, _token_from(sent[0])) is None
