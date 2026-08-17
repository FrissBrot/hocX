from fastapi import HTTPException

from app.core.secret_crypto import encrypt_secret
from app.core.security import build_current_user, create_session_token, get_optional_current_user
from app.core.totp import current_totp_code, generate_totp_secret
from app.models import UserMfaFactor
from app.services.mfa_service import MfaService
from tests.factories import make_app_user, make_tenant, make_user_tenant_role


def test_session_without_mfa_flag_is_rejected_when_factor_exists(db):
    tenant = make_tenant(db)
    user = make_app_user(db, email="mfa-user@example.com")
    make_user_tenant_role(db, user.id, tenant.id, role_code="writer")
    db.add(
        UserMfaFactor(
            user_id=user.id,
            factor_type="totp",
            label="Authenticator App",
            secret_encrypted=encrypt_secret(generate_totp_secret()),
        )
    )
    db.flush()

    token = create_session_token(user.id, tenant.id, mfa_verified=False)
    assert get_optional_current_user(request=None, db=db, session_cookie=token) is None


def test_admin_without_factor_session_is_rejected(db):
    tenant = make_tenant(db)
    user = make_app_user(db, email="admin-no-mfa@example.com")
    make_user_tenant_role(db, user.id, tenant.id, role_code="admin")

    token = create_session_token(user.id, tenant.id, mfa_verified=False)
    assert get_optional_current_user(request=None, db=db, session_cookie=token) is None


def test_prepare_login_requires_setup_for_admin_without_factor(db):
    tenant = make_tenant(db)
    user = make_app_user(db, email="setup-required@example.com")
    make_user_tenant_role(db, user.id, tenant.id, role_code="admin")

    service = MfaService()
    current_user = build_current_user(db, user, tenant.id)
    pending = service.prepare_login(db, user=user, current_user=current_user, request_host="app.example.com")

    assert pending is not None
    assert pending.status == "setup_required"
    assert pending.required is True


def test_verify_login_totp_completes_pending_ticket(db):
    tenant = make_tenant(db)
    user = make_app_user(db, email="totp-login@example.com")
    make_user_tenant_role(db, user.id, tenant.id, role_code="writer")
    secret = generate_totp_secret()
    db.add(
        UserMfaFactor(
            user_id=user.id,
            factor_type="totp",
            label="Auth App",
            secret_encrypted=encrypt_secret(secret),
        )
    )
    db.flush()

    service = MfaService()
    current_user = build_current_user(db, user, tenant.id)
    pending = service.prepare_login(db, user=user, current_user=current_user, request_host="app.example.com")
    assert pending is not None
    assert pending.status == "verification_required"

    context = service.verify_login_totp(db, ticket=pending.ticket, code=current_totp_code(secret))

    assert context.user.id == user.id
    assert context.current_user.current_tenant_id == tenant.id


def test_prepare_login_uses_saved_default_method(db):
    tenant = make_tenant(db)
    user = make_app_user(db, email="preferred-method@example.com")
    user.preferred_mfa_factor_type = "totp"
    make_user_tenant_role(db, user.id, tenant.id, role_code="writer")
    db.add(
        UserMfaFactor(
            user_id=user.id,
            factor_type="totp",
            label="Auth App",
            secret_encrypted=encrypt_secret(generate_totp_secret()),
        )
    )
    db.add(
        UserMfaFactor(
            user_id=user.id,
            factor_type="webauthn",
            label="Laptop Passkey",
            webauthn_credential_id="credential-preferred-method",
        )
    )
    db.flush()

    service = MfaService()
    current_user = build_current_user(db, user, tenant.id)
    pending = service.prepare_login(db, user=user, current_user=current_user, request_host="app.example.com")

    assert pending is not None
    assert pending.default_factor_type == "totp"
    assert pending.default_factor_label == "Authenticator-App"


def test_set_self_preferred_method_updates_overview(db):
    tenant = make_tenant(db)
    user = make_app_user(db, email="switch-preferred@example.com")
    make_user_tenant_role(db, user.id, tenant.id, role_code="writer")
    db.add(
        UserMfaFactor(
            user_id=user.id,
            factor_type="totp",
            label="Auth App",
            secret_encrypted=encrypt_secret(generate_totp_secret()),
        )
    )
    db.add(
        UserMfaFactor(
            user_id=user.id,
            factor_type="webauthn",
            label="Phone Passkey",
            webauthn_credential_id="credential-switch-preferred",
        )
    )
    db.flush()

    service = MfaService()
    actor = build_current_user(db, user, tenant.id, mfa_verified=True)
    overview = service.set_self_preferred_method(
        db,
        actor,
        factor_type="webauthn",
        request_host="app.example.com",
    )

    assert overview.preferred_factor_type == "webauthn"
    assert overview.preferred_factor_label == "Passkey"


def test_delete_self_factor_blocks_last_factor_for_required_user(db):
    tenant = make_tenant(db)
    user = make_app_user(db, email="required-reset@example.com")
    make_user_tenant_role(db, user.id, tenant.id, role_code="admin")
    factor = UserMfaFactor(
        user_id=user.id,
        factor_type="totp",
        label="Auth App",
        secret_encrypted=encrypt_secret(generate_totp_secret()),
    )
    db.add(factor)
    db.flush()

    service = MfaService()
    actor = build_current_user(db, user, tenant.id, mfa_verified=True)

    try:
        service.delete_self_factor(db, actor, factor.id)
        assert False, "expected delete_self_factor to block removing the last required factor"
    except HTTPException as exc:
        assert exc.status_code == 409
