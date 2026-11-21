"""Signal «neues Land» (Auth-Audit 7.2) und Anzeige des Landes - mit kleiner Test-MMDB.

Nur der Ländercode wird gespeichert (auth_event, Session, Gerät), nie die IP. Ohne Baseline (keine
frühere Anmeldung mit bekanntem Land) entsteht kein Signal; allein entscheidet es nie.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text

from app.auth_security import events, risk
from app.auth_security.guard import baseline_signals
from app.core import audit_context, geoip
from app.core.config import settings
from app.models import AuthEvent, AuthKnownDevice, AuthSession
from tests.factories import make_app_user, make_tenant
from tests.mmdb_fixture import write_mmdb
from tests.test_auth_hardening import _clean, _known_device, _login, _remove_committed_tenants  # noqa: F401 - autouse-Fixtures

CH_IP = "81.62.10.20"
DE_IP = "5.9.10.20"


@pytest.fixture(autouse=True)
def geo_db(tmp_path, monkeypatch):
    path = write_mmdb(tmp_path / "dbip-country-lite.mmdb", {"81.0.0.0/8": "CH", "5.0.0.0/8": "DE"})
    monkeypatch.setattr(settings, "geoip_db_path", str(path))
    geoip.reset()
    yield path
    geoip.reset()


@contextmanager
def _client(ip: str):
    token = audit_context._client_ip.set(ip)
    try:
        yield
    finally:
        audit_context._client_ip.reset(token)


def test_new_country_weighs_ten_and_is_never_decisive_alone():
    alone = risk.assess(risk.Signals(known_device=True, new_country=True))
    assert (alone.score, alone.reasons, alone.level) == (risk.NEW_COUNTRY_WEIGHT, ["new_country"], risk.NORMAL)
    assert risk.NEW_COUNTRY_WEIGHT < settings.auth_risk_moderate
    assert "new_country" not in risk.assess(risk.Signals(known_device=True, new_country=None)).reasons
    assert "new_country" not in risk.assess(risk.Signals(known_device=True, new_country=False)).reasons


def _success(db, user, country: str | None) -> None:
    events.record(event_type="login.success", outcome="success", user_id=user.id, tenant_id=user.tenant_id)
    db.execute(
        text("UPDATE auth_event SET src_country = :c WHERE id = (SELECT max(id) FROM auth_event WHERE actor_user_id = :id)"),
        {"c": country, "id": user.id},
    )
    db.commit()


def test_baseline_needs_a_previous_login_with_known_country(db):
    user = make_app_user(db, email="geo-baseline@example.com", tenant_id=make_tenant(db).id)
    db.commit()
    # Keine Anmeldung: keine Baseline
    assert baseline_signals(db, user_id=user.id, net_hash=None, country="DE")[2] is None
    # Anmeldungen ohne Land (GeoIP fehlte damals): weiterhin keine Baseline
    _success(db, user, None)
    assert baseline_signals(db, user_id=user.id, net_hash=None, country="DE")[2] is None
    # Mit Baseline CH
    _success(db, user, "CH")
    assert baseline_signals(db, user_id=user.id, net_hash=None, country="DE")[2] is True
    assert baseline_signals(db, user_id=user.id, net_hash=None, country="CH")[2] is False
    # Aktuelles Land unbekannt (keine DB, private Adresse): kein Signal
    assert baseline_signals(db, user_id=user.id, net_hash=None, country=None)[2] is None
    # Fehlversuche aus einem Land zählen nicht als Baseline
    events.record(event_type="login.password", outcome="failure", user_id=user.id, tenant_id=user.tenant_id)
    db.execute(text("UPDATE auth_event SET src_country = 'DE' WHERE actor_user_id = :id AND outcome = 'failure'"), {"id": user.id})
    db.commit()
    assert baseline_signals(db, user_id=user.id, net_hash=None, country="DE")[2] is True


def test_login_stores_only_the_country_and_flags_a_new_one(db):
    tenant = make_tenant(db)
    user = make_app_user(db, email="geo-login@example.com", tenant_id=tenant.id, role_code="writer")
    user.first_login_at = datetime.now(UTC)
    cookies = _known_device(db, user)
    db.commit()
    with _client(CH_IP):
        result, _ = _login(db, user.email, ip=CH_IP, cookies=cookies)
    assert result.authenticated
    first = db.scalars(select(AuthEvent).where(AuthEvent.actor_user_id == user.id, AuthEvent.event_type == "login.success")).all()
    assert [row.src_country for row in first] == ["CH"]
    assert "new_country" not in first[0].risk_reasons  # erste Anmeldung mit Land: keine Baseline
    session = db.scalars(select(AuthSession).where(AuthSession.user_id == user.id)).one()
    assert session.country == "CH"
    assert db.scalars(select(AuthKnownDevice.last_country).where(AuthKnownDevice.user_id == user.id)).one() == "CH"
    # Nirgends die IP im Klartext
    row = db.execute(text("SELECT row_to_json(e)::text FROM auth_event e WHERE e.actor_user_id = :id"), {"id": user.id}).scalar()
    assert CH_IP not in row

    with _client(DE_IP):
        result, _ = _login(db, user.email, ip=DE_IP, cookies=cookies)
    assert result.authenticated  # bekanntes Gerät + neues Land + neues Netz = 20 < moderat
    db.expire_all()
    latest = db.scalars(
        select(AuthEvent).where(AuthEvent.actor_user_id == user.id, AuthEvent.event_type == "login.success").order_by(AuthEvent.id.desc())
    ).first()
    assert latest.src_country == "DE" and "new_country" in latest.risk_reasons


def test_without_geoip_database_no_country_and_no_signal(db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "geoip_db_path", str(tmp_path / "fehlt.mmdb"))
    geoip.reset()
    tenant = make_tenant(db)
    user = make_app_user(db, email="geo-none@example.com", tenant_id=tenant.id, role_code="writer")
    user.first_login_at = datetime.now(UTC)
    cookies = _known_device(db, user)
    _success(db, user, "CH")
    with _client(DE_IP):
        result, _ = _login(db, user.email, ip=DE_IP, cookies=cookies)
    assert result.authenticated
    db.expire_all()
    latest = db.scalars(
        select(AuthEvent).where(AuthEvent.actor_user_id == user.id, AuthEvent.event_type == "login.success").order_by(AuthEvent.id.desc())
    ).first()
    assert latest.src_country is None and "new_country" not in latest.risk_reasons


def test_country_check_constraint_rejects_anything_but_two_letters(db):
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError), db.begin_nested():
        db.execute(text("INSERT INTO auth_event (event_type, outcome, src_country) VALUES ('login.success', 'success', '81.62.10.20')"))


def test_login_mails_show_the_translated_country_with_source():
    from app.core.locale_config_generated import SUPPORTED_LOCALES
    from app.notifications.render import render

    for lang in SUPPORTED_LOCALES:
        rendered = render(
            lang=lang, group="account.login_alert", recipient_name="Anna", tenant_name="Verein", base_url="https://app.example.com", can_login=True,
            items=[{"kind": "security.login_suspicious", "at": datetime.now(UTC), "device": "Firefox · Linux", "country": "CH", "reasons": ["new_country"], "count": 0}],
        )
        name = geoip.country_name("CH", lang)
        assert name in rendered.text and name in rendered.html
        assert "DB-IP" in rendered.text and "CC BY 4.0" in rendered.text
        assert "email.login" not in rendered.text and "{" not in rendered.text
        notice = render(
            lang=lang, group="account.login_notice", recipient_name="Anna", tenant_name="Verein", base_url="https://app.example.com", can_login=True,
            items=[{"kind": "security.login_new_device", "at": datetime.now(UTC), "device": "Safari · iOS", "reasons": [], "count": 0}],
        )
        # Ohne Land keine Quellenangabe
        assert "DB-IP" not in notice.text


def test_session_list_shows_the_country(db):
    from app.api.routes import users as users_route
    from app.auth_security import devices
    from app.core.security import get_optional_current_user
    from tests.test_auth_hardening import _req, _session_token

    tenant = make_tenant(db)
    user = make_app_user(db, email="geo-list@example.com", tenant_id=tenant.id, role_code="writer")
    user.first_login_at = datetime.now(UTC)
    cookies = _known_device(db, user)
    db.commit()
    with _client(CH_IP):
        _result, response = _login(db, user.email, ip=CH_IP, cookies=cookies)
    current = get_optional_current_user(request=None, db=db, session_cookie=_session_token(response))
    listing = users_route.list_my_sessions(db=db, user=current)
    assert [item.country for item in listing.sessions] == ["CH"]
    known = users_route.list_my_devices(_req(cookies), db=db, user=current)
    assert {item.country for item in known} == {"CH"}
    assert devices.cookie_name() in cookies
