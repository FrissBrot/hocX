"""Verifies the make_mfa_enrolled_user() test fixture (factories.py) actually behaves like a
real MFA-enrolled account end-to-end: password login returns "verification_required" (not
"setup_required"), a correct TOTP code completes the login, and a wrong one is rejected."""

import pytest
from fastapi import HTTPException, Response

from app.core.totp import current_totp_code
from app.schemas.mfa import TotpLoginVerifyRequest
from app.schemas.user import LoginRequest
from app.services.auth_service import AuthService
from tests.factories import make_mfa_enrolled_user, make_tenant


def test_login_of_an_mfa_enrolled_user_asks_for_verification_not_setup(db):
    tenant = make_tenant(db)
    user, _secret = make_mfa_enrolled_user(db, email="mfa1@example.com", tenant_id=tenant.id)

    result = AuthService().login(db, Response(), LoginRequest(email="mfa1@example.com", password="correct horse battery staple"))

    assert result.authenticated is False
    assert result.mfa is not None
    assert result.mfa.status == "verification_required"
    assert result.mfa.ticket


def test_a_valid_totp_code_completes_the_login(db):
    tenant = make_tenant(db)
    user, secret = make_mfa_enrolled_user(db, email="mfa2@example.com", tenant_id=tenant.id)
    service = AuthService()
    pending = service.login(db, Response(), LoginRequest(email="mfa2@example.com", password="correct horse battery staple"))

    result = service.verify_login_totp(
        db, Response(), TotpLoginVerifyRequest(ticket=pending.mfa.ticket, code=current_totp_code(secret))
    )

    assert result.authenticated is True
    assert result.user is not None
    assert result.user.email == "mfa2@example.com"


def test_an_incorrect_totp_code_is_rejected(db):
    tenant = make_tenant(db)
    _user, secret = make_mfa_enrolled_user(db, email="mfa3@example.com", tenant_id=tenant.id)
    service = AuthService()
    pending = service.login(db, Response(), LoginRequest(email="mfa3@example.com", password="correct horse battery staple"))
    wrong_code = str((int(current_totp_code(secret)) + 1) % 1_000_000).zfill(6)

    with pytest.raises(HTTPException) as exc_info:
        service.verify_login_totp(db, Response(), TotpLoginVerifyRequest(ticket=pending.mfa.ticket, code=wrong_code))
    assert exc_info.value.status_code == 401
