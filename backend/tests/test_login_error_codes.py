"""Fehler der Anmeldung tragen einen stabilen Code (`detail = {code, message}`), damit die
Login-Seite sie in der UI-Sprache anzeigt (security.apiErrors.<code>) statt den deutschen
Backend-Text - wie schon `invalid_credentials`. `message` bleibt als deutscher Fallback."""
import pytest
from fastapi import HTTPException

from app.core.secret_crypto import encrypt_secret
from app.core.security import build_current_user
from app.core.totp import generate_totp_secret
from app.models import UserMfaFactor
from app.services.mfa_service import MfaService
from tests.factories import make_app_user, make_tenant


def _user_with_totp(db, email):
    tenant = make_tenant(db)
    user = make_app_user(db, email=email, tenant_id=tenant.id, role_code="writer")
    db.add(UserMfaFactor(user_id=user.id, factor_type="totp", label="Auth App", secret_encrypted=encrypt_secret(generate_totp_secret())))
    db.flush()
    return user


def _code(exc: HTTPException) -> str | None:
    return exc.detail.get("code") if isinstance(exc.detail, dict) else None


def test_wrong_totp_code_at_login_has_a_stable_code(db):
    user = _user_with_totp(db, "code-totp@example.com")
    service = MfaService()
    pending = service.prepare_login(db, user=user, current_user=build_current_user(db, user), request_host="app.example.com")

    with pytest.raises(HTTPException) as exc_info:
        service.verify_login_totp(db, ticket=pending.ticket, code="000000")

    assert exc_info.value.status_code == 401
    assert _code(exc_info.value) == "totp_invalid"
    assert exc_info.value.detail["message"]


def test_expired_mfa_ticket_has_a_stable_code(db):
    with pytest.raises(HTTPException) as exc_info:
        MfaService().verify_login_totp(db, ticket="gibt-es-nicht", code="000000")

    assert exc_info.value.status_code == 401
    assert _code(exc_info.value) == "mfa_flow_expired"


def test_disabled_login_during_mfa_has_a_stable_code(db):
    user = _user_with_totp(db, "code-disabled@example.com")
    service = MfaService()
    pending = service.prepare_login(db, user=user, current_user=build_current_user(db, user), request_host="app.example.com")
    user.login_enabled = False
    db.flush()

    with pytest.raises(HTTPException) as exc_info:
        service.verify_login_totp(db, ticket=pending.ticket, code="000000")

    assert exc_info.value.status_code == 403
    assert _code(exc_info.value) == "login_disabled"
