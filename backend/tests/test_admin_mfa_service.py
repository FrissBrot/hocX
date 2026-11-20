"""Plattform-Admins: nur Passwort + Passkey, erzwungen (AdminMfaService, Migration 0205).

Abgedeckt: Login mit Passkey (inkl. falscher Origin, falscher RP-ID, Wiederverwendung der
Challenge, fremder Schlüssel, Konto-Sperre), Pflicht-Einrichtung ohne Passkey (Trust on first use,
keine Session davor), Selbstverwaltung (letzter Passkey nicht entfernbar), kein TOTP-Weg mehr,
Session-Claim, Notausgang (admin_cli)."""
from __future__ import annotations

import pytest
from fastapi import HTTPException, Response
from sqlalchemy import select, text

from app.core.admin_security import CurrentAdmin, create_admin_session_token, parse_admin_session_token
from app.core.secret_crypto import encrypt_secret
from app.core.totp import generate_totp_secret
from app.models.entities import PlatformAdmin, UserMfaFactor
from app.schemas.admin import AdminLoginRequest
from app.services import admin_mfa_service as mfa_module
from app.services.admin_auth_service import AdminAuthService
from app.services.admin_mfa_service import AdminMfaService
from tests.soft_passkey import SoftPasskey

RP_ID = "admin.hocx.example"
ORIGIN = f"https://{RP_ID}"
PASSWORD = "admin-password-lang"


@pytest.fixture(autouse=True)
def _admin_domain(monkeypatch):
    monkeypatch.setattr(mfa_module.settings, "traefik_admin_domain", RP_ID)


def _make_admin(db, email: str) -> PlatformAdmin:
    from app.core.security import hash_password

    admin = PlatformAdmin(email=email, password_hash=hash_password(PASSWORD), display_name="Ops")
    db.add(admin)
    db.flush()
    return admin


def _actor(admin: PlatformAdmin) -> CurrentAdmin:
    return CurrentAdmin(admin_id=admin.id, admin_public_id=admin.public_id, email=admin.email, display_name=admin.display_name)


def _login(db, email: str):
    return AdminAuthService().login(db, Response(), AdminLoginRequest(email=email, password=PASSWORD))


def _enroll_via_login(db, admin: PlatformAdmin, passkey: SoftPasskey) -> Response:
    pending = _login(db, admin.email)
    assert pending.mfa.status == "setup_required"
    service = AdminAuthService()
    start = service.start_login_passkey_setup(db, ticket=pending.mfa.ticket, request_host="ignored", request_origin=ORIGIN)
    response = Response()
    session = service.complete_login_passkey_setup(
        db, response, flow_token=start.flow_token, label="YubiKey", credential=passkey.create(start.public_key, origin=ORIGIN)
    )
    assert session.authenticated is True
    return response


def _session_cookie(response: Response) -> str:
    header = response.headers["set-cookie"]
    return header.split("=", 1)[1].split(";", 1)[0]


def test_admin_without_passkey_must_enroll_one_before_any_session(db):
    admin = _make_admin(db, "tofu@example.com")
    pending = _login(db, admin.email)

    assert pending.authenticated is False
    assert pending.mfa.status == "setup_required"
    assert pending.mfa.can_add_totp is False and pending.mfa.can_add_passkey is True
    # Kein Passkey vorhanden -> eine Bestätigung ist unmöglich, nur die Einrichtung
    with pytest.raises(HTTPException) as exc_info:
        AdminAuthService().start_login_passkey(db, ticket=pending.mfa.ticket, request_host=None, request_origin=ORIGIN)
    assert exc_info.value.status_code == 400

    response = _enroll_via_login(db, admin, SoftPasskey())
    token = _session_cookie(response)
    data = parse_admin_session_token(token)
    assert data["amr"] == "passkey" and data["mfa"] is True
    assert "samesite=strict" in response.headers["set-cookie"].lower()
    factor = db.scalars(select(UserMfaFactor).where(UserMfaFactor.platform_admin_id == admin.id)).one()
    assert factor.factor_type == "webauthn" and factor.webauthn_rp_id == RP_ID and factor.label == "YubiKey"


def test_login_with_registered_passkey(db):
    admin = _make_admin(db, "login@example.com")
    passkey = SoftPasskey()
    _enroll_via_login(db, admin, passkey)

    pending = _login(db, admin.email)
    assert pending.mfa.status == "verification_required"
    assert [m.factor_type for m in pending.mfa.available_methods] == ["webauthn"]
    assert pending.mfa.can_add_passkey is False  # MAIN-SEC-001: im Login kein zweiter Passkey
    service = AdminAuthService()
    start = service.start_login_passkey(db, ticket=pending.mfa.ticket, request_host=None, request_origin=ORIGIN)
    assert start.public_key["rpId"] == RP_ID
    assert start.public_key["userVerification"] == "required"
    session = service.verify_login_passkey(db, Response(), flow_token=start.flow_token, credential=passkey.get(start.public_key, origin=ORIGIN))
    assert session.authenticated is True

    # Setup im Login ist mit vorhandenem Passkey gesperrt (sonst genügte das Passwort für einen zweiten)
    pending = _login(db, admin.email)
    with pytest.raises(HTTPException) as exc_info:
        service.start_login_passkey_setup(db, ticket=pending.mfa.ticket, request_host=None, request_origin=ORIGIN)
    assert exc_info.value.status_code == 403


@pytest.mark.parametrize(
    "tamper",
    [
        {"origin": "https://evil.example"},
        {"origin": "https://admin.hocx.example:8443"},
        {"rp_id": "hocx.example"},
        {"rp_id": "evil.example"},
    ],
)
def test_passkey_login_rejects_wrong_origin_or_rp_id(db, tamper):
    admin = _make_admin(db, f"tamper-{len(str(tamper))}-{sorted(tamper)[0]}@example.com")
    passkey = SoftPasskey()
    _enroll_via_login(db, admin, passkey)
    pending = _login(db, admin.email)
    service = AdminAuthService()
    start = service.start_login_passkey(db, ticket=pending.mfa.ticket, request_host=None, request_origin=ORIGIN)
    credential = passkey.get(start.public_key, origin=tamper.get("origin", ORIGIN), rp_id=tamper.get("rp_id"))

    with pytest.raises(HTTPException) as exc_info:
        service.verify_login_passkey(db, Response(), flow_token=start.flow_token, credential=credential)
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail["code"] == "passkey_invalid"


def test_passkey_challenge_cannot_be_reused(db):
    admin = _make_admin(db, "replay@example.com")
    passkey = SoftPasskey()
    _enroll_via_login(db, admin, passkey)
    pending = _login(db, admin.email)
    service = AdminAuthService()
    start = service.start_login_passkey(db, ticket=pending.mfa.ticket, request_host=None, request_origin=ORIGIN)
    credential = passkey.get(start.public_key, origin=ORIGIN)
    service.verify_login_passkey(db, Response(), flow_token=start.flow_token, credential=credential)

    with pytest.raises(HTTPException) as exc_info:
        service.verify_login_passkey(db, Response(), flow_token=start.flow_token, credential=credential)
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail["code"] == "mfa_flow_expired"


def test_failed_challenge_is_consumed_too(db):
    """Auch eine fehlgeschlagene Prüfung verbraucht die Challenge - kein zweiter Versuch damit."""
    admin = _make_admin(db, "consumed@example.com")
    passkey = SoftPasskey()
    _enroll_via_login(db, admin, passkey)
    pending = _login(db, admin.email)
    service = AdminAuthService()
    start = service.start_login_passkey(db, ticket=pending.mfa.ticket, request_host=None, request_origin=ORIGIN)
    with pytest.raises(HTTPException):
        service.verify_login_passkey(db, Response(), flow_token=start.flow_token, credential=SoftPasskey().get(start.public_key, origin=ORIGIN))
    with pytest.raises(HTTPException) as exc_info:
        service.verify_login_passkey(db, Response(), flow_token=start.flow_token, credential=passkey.get(start.public_key, origin=ORIGIN))
    assert exc_info.value.detail["code"] == "mfa_flow_expired"


def test_foreign_admins_passkey_is_rejected(db):
    victim = _make_admin(db, "victim@example.com")
    attacker = _make_admin(db, "attacker@example.com")
    attacker_key = SoftPasskey()
    _enroll_via_login(db, victim, SoftPasskey())
    _enroll_via_login(db, attacker, attacker_key)
    pending = _login(db, victim.email)
    service = AdminAuthService()
    start = service.start_login_passkey(db, ticket=pending.mfa.ticket, request_host=None, request_origin=ORIGIN)
    with pytest.raises(HTTPException) as exc_info:
        service.verify_login_passkey(db, Response(), flow_token=start.flow_token, credential=attacker_key.get(start.public_key, origin=ORIGIN))
    assert exc_info.value.detail["code"] == "passkey_unknown"


def test_passkey_without_user_verification_is_rejected(db):
    admin = _make_admin(db, "nouv@example.com")
    passkey = SoftPasskey()
    _enroll_via_login(db, admin, passkey)
    passkey.user_verified = False
    pending = _login(db, admin.email)
    service = AdminAuthService()
    start = service.start_login_passkey(db, ticket=pending.mfa.ticket, request_host=None, request_origin=ORIGIN)
    with pytest.raises(HTTPException):
        service.verify_login_passkey(db, Response(), flow_token=start.flow_token, credential=passkey.get(start.public_key, origin=ORIGIN))


def test_account_lockout_after_repeated_failures(db, monkeypatch):
    admin = _make_admin(db, "lockout@example.com")
    _enroll_via_login(db, admin, SoftPasskey())
    service = AdminAuthService()
    stranger = SoftPasskey()
    for _ in range(mfa_module._ACCOUNT_ATTEMPT_LIMIT):
        pending = _login(db, admin.email)
        start = service.start_login_passkey(db, ticket=pending.mfa.ticket, request_host=None, request_origin=ORIGIN)
        with pytest.raises(HTTPException):
            service.verify_login_passkey(db, Response(), flow_token=start.flow_token, credential=stranger.get(start.public_key, origin=ORIGIN))
    pending = _login(db, admin.email)
    start = service.start_login_passkey(db, ticket=pending.mfa.ticket, request_host=None, request_origin=ORIGIN)
    with pytest.raises(HTTPException) as exc_info:
        service.verify_login_passkey(db, Response(), flow_token=start.flow_token, credential=stranger.get(start.public_key, origin=ORIGIN))
    assert exc_info.value.status_code == 429


def test_no_totp_path_for_admins(db):
    """TOTP ist für Admins vollständig entfernt: kein Service-Weg, kein Login-Angebot, und die
    Datenbank nimmt keinen Admin-TOTP-Faktor mehr an (0205)."""
    service = AdminMfaService()
    for name in ("start_self_totp_enrollment", "complete_self_totp_enrollment", "verify_login_totp",
                 "start_login_totp_enrollment", "complete_login_totp_enrollment", "verify_step_up_totp"):
        assert not hasattr(service, name), name
    admin = _make_admin(db, "legacy-totp@example.com")
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.add(UserMfaFactor(platform_admin_id=admin.id, factor_type="totp", label="alt",
                                 secret_encrypted=encrypt_secret(generate_totp_secret())))
            db.flush()


def test_session_without_passkey_claim_is_rejected(db):
    """TOTP-/SSO-Sessions bis 1.4.x tragen keinen amr=passkey und gelten nicht mehr."""
    import base64
    import hashlib
    import hmac
    import json
    from datetime import UTC, datetime

    from app.core.admin_security import get_optional_current_admin
    from app.core.config import settings
    from starlette.requests import Request

    admin = _make_admin(db, "oldsession@example.com")
    now = int(datetime.now(UTC).timestamp())
    payload = json.dumps({"admin_id": admin.id, "mfa": True, "iat": now, "exp": now + 3600}, separators=(",", ":")).encode()
    signature = hmac.new(settings.admin_auth_secret.encode(), payload, hashlib.sha256).digest()
    old_token = base64.urlsafe_b64encode(payload).decode() + "." + base64.urlsafe_b64encode(signature).decode()
    request = Request({"type": "http", "headers": []})
    assert get_optional_current_admin(request, db, old_token) is None
    assert get_optional_current_admin(request, db, create_admin_session_token(admin.id)) is not None


def test_self_service_last_passkey_cannot_be_removed(db):
    admin = _make_admin(db, "self@example.com")
    _enroll_via_login(db, admin, SoftPasskey())
    service = AdminMfaService()
    actor = _actor(admin)
    overview = service.get_self_overview(db, actor)
    assert overview.required and len(overview.factors) == 1 and overview.factors[0].factor_type == "webauthn"
    only = db.scalars(select(UserMfaFactor).where(UserMfaFactor.platform_admin_id == admin.id)).one()
    with pytest.raises(HTTPException) as exc_info:
        service.delete_self_factor(db, actor, only.id)
    assert exc_info.value.status_code == 409 and exc_info.value.detail["code"] == "last_passkey"

    start = service.start_self_passkey_registration(db, actor, request_host=None, request_origin=ORIGIN)
    assert start.public_key["rp"]["id"] == RP_ID
    assert start.public_key["excludeCredentials"][0]["id"] == only.webauthn_credential_id
    service.complete_self_passkey_registration(db, actor, flow_token=start.flow_token, label=None,
                                               credential=SoftPasskey().create(start.public_key, origin=ORIGIN))
    assert len(service.delete_self_factor(db, actor, only.id).factors) == 1


def test_self_registration_flow_is_single_use_and_bound_to_admin(db):
    admin = _make_admin(db, "bound@example.com")
    other = _make_admin(db, "bound-other@example.com")
    service = AdminMfaService()
    start = service.start_self_passkey_registration(db, _actor(admin), request_host=None, request_origin=ORIGIN)
    credential = SoftPasskey().create(start.public_key, origin=ORIGIN)
    with pytest.raises(HTTPException) as exc_info:
        service.complete_self_passkey_registration(db, _actor(other), flow_token=start.flow_token, label=None, credential=credential)
    assert exc_info.value.status_code == 403
    # Vorgang ist durch den Fehlversuch verbraucht
    with pytest.raises(HTTPException) as exc_info:
        service.complete_self_passkey_registration(db, _actor(admin), flow_token=start.flow_token, label=None, credential=credential)
    assert exc_info.value.status_code == 401


def test_registration_with_wrong_origin_is_rejected(db):
    admin = _make_admin(db, "regorigin@example.com")
    service = AdminMfaService()
    start = service.start_self_passkey_registration(db, _actor(admin), request_host=None, request_origin=ORIGIN)
    with pytest.raises(HTTPException) as exc_info:
        service.complete_self_passkey_registration(db, _actor(admin), flow_token=start.flow_token, label=None,
                                                   credential=SoftPasskey().create(start.public_key, origin="https://evil.example"))
    assert exc_info.value.status_code == 400


def test_admin_cli_reset_passkeys_revokes_sessions_and_forces_new_setup(db, monkeypatch, capsys):
    from contextlib import contextmanager

    from app import admin_cli

    admin = _make_admin(db, "cli@example.com")
    token = _session_cookie(_enroll_via_login(db, admin, SoftPasskey()))
    pending_before = _login(db, admin.email)

    @contextmanager
    def same_session():
        yield db

    monkeypatch.setattr(admin_cli, "SessionLocal", same_session)
    assert admin_cli.main(["reset-passkeys", "--email", admin.email]) == 0
    assert "1 Passkey(s)" in capsys.readouterr().out

    assert db.scalars(select(UserMfaFactor).where(UserMfaFactor.platform_admin_id == admin.id)).all() == []
    from app.core.admin_security import get_optional_current_admin
    from starlette.requests import Request

    assert get_optional_current_admin(Request({"type": "http", "headers": []}), db, token) is None
    # Ein vor dem Zurücksetzen ausgestelltes Login-Ticket gilt nicht mehr
    with pytest.raises(HTTPException):
        AdminAuthService().start_login_passkey_setup(db, ticket=pending_before.mfa.ticket, request_host=None, request_origin=ORIGIN)
    assert _login(db, admin.email).mfa.status == "setup_required"
    assert db.execute(
        text("SELECT 1 FROM audit_log WHERE action = 'admin.passkeys_reset' AND actor_email = 'cli' AND entity_id = :id"), {"id": admin.id}
    ).first() is not None
    assert admin_cli.main(["reset-passkeys", "--email", "gibt-es-nicht@example.com"]) == 1


def test_admin_cli_reset_password(db, monkeypatch, capsys):
    from contextlib import contextmanager

    from app import admin_cli
    from app.core.security import verify_password

    admin = _make_admin(db, "cli-password@example.com")
    token = _session_cookie(_enroll_via_login(db, admin, SoftPasskey()))

    @contextmanager
    def same_session():
        yield db

    monkeypatch.setattr(admin_cli, "SessionLocal", same_session)
    assert admin_cli.main(["reset-password", "--email", admin.email]) == 0
    new_password = capsys.readouterr().out.strip().splitlines()[-1]
    assert len(new_password) >= 20
    db.refresh(admin)
    assert verify_password(new_password, admin.password_hash) and not verify_password(PASSWORD, admin.password_hash)
    from app.core.admin_security import get_optional_current_admin
    from starlette.requests import Request

    assert get_optional_current_admin(Request({"type": "http", "headers": []}), db, token) is None
    assert db.execute(
        text("SELECT 1 FROM audit_log WHERE action = 'admin.password_reset' AND actor_email = 'cli' AND entity_id = :id"), {"id": admin.id}
    ).first() is not None


def test_session_revoked_in_the_same_second_counts(db):
    """Review L5: Widerruf in Millisekunden - ein Token, das vor dem Widerruf (auch in derselben
    Sekunde) ausgestellt wurde, gilt nicht mehr; eines danach schon."""
    from datetime import UTC, datetime, timedelta

    from app.core.admin_security import get_optional_current_admin
    from starlette.requests import Request

    admin = _make_admin(db, "same-second@example.com")
    before = create_admin_session_token(admin.id)
    admin.session_revoke_at = datetime.now(UTC)
    db.flush()
    request = Request({"type": "http", "headers": []})
    assert get_optional_current_admin(request, db, before) is None
    admin.session_revoke_at = datetime.now(UTC) - timedelta(milliseconds=50)
    db.flush()
    assert get_optional_current_admin(request, db, create_admin_session_token(admin.id)) is not None


def test_sign_counter_regression_locks_passkey_and_alerts(db, monkeypatch):
    """Review L8: Zähler läuft zurück (geklonter Schlüssel?) -> Passkey gesperrt, Systemcheck kritisch."""
    from app.services import system_health_service

    recorded: list[Exception] = []
    import app.core.error_log as error_log

    monkeypatch.setattr(error_log, "record_system_error", lambda db, *, exc, **_kw: recorded.append(exc))
    admin = _make_admin(db, "clone@example.com")
    passkey = SoftPasskey()
    _enroll_via_login(db, admin, passkey)
    service = AdminAuthService()
    for _ in range(2):  # Zähler steigt auf 2
        pending = _login(db, admin.email)
        start = service.start_login_passkey(db, ticket=pending.mfa.ticket, request_host=None, request_origin=ORIGIN)
        service.verify_login_passkey(db, Response(), flow_token=start.flow_token, credential=passkey.get(start.public_key, origin=ORIGIN))

    passkey.sign_count = 0  # Klon mit altem Zählerstand
    pending = _login(db, admin.email)
    start = service.start_login_passkey(db, ticket=pending.mfa.ticket, request_host=None, request_origin=ORIGIN)
    with pytest.raises(HTTPException) as exc_info:
        service.verify_login_passkey(db, Response(), flow_token=start.flow_token, credential=passkey.get(start.public_key, origin=ORIGIN))
    assert exc_info.value.detail == {"code": "passkey_invalid", "message": "Der Passkey konnte nicht geprüft werden"}
    factor = db.scalars(select(UserMfaFactor).where(UserMfaFactor.platform_admin_id == admin.id)).one()
    assert factor.locked_at is not None
    assert recorded and "gesperrt" in str(recorded[0])

    # Gesperrt: auch der «richtige» Schlüssel kommt nicht mehr durch, nur der Notausgang hilft
    passkey.sign_count = 100
    pending = _login(db, admin.email)
    with pytest.raises(HTTPException):
        service.start_login_passkey(db, ticket=pending.mfa.ticket, request_host=None, request_origin=ORIGIN)
    check = system_health_service._check_admin_passkeys(db)
    assert check.status == "critical" and check.params["count"] >= 1
