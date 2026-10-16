from fastapi import HTTPException

from app.core.secret_crypto import encrypt_secret
from app.core.security import build_current_user, create_session_token, get_optional_current_user
from app.core.totp import current_totp_code, generate_totp_secret
from app.models import UserMfaFactor
from app.services.mfa_service import _ACCOUNT_TOTP_ATTEMPT_LIMIT, MfaService
from tests.factories import make_app_user, make_tenant


def test_session_without_mfa_flag_is_rejected_when_factor_exists(db):
    tenant = make_tenant(db)
    user = make_app_user(db, email="mfa-user@example.com", tenant_id=tenant.id, role_code="writer")
    db.add(
        UserMfaFactor(
            user_id=user.id,
            factor_type="totp",
            label="Authenticator App",
            secret_encrypted=encrypt_secret(generate_totp_secret()),
        )
    )
    db.flush()

    token = create_session_token(user.id, mfa_verified=False)
    assert get_optional_current_user(request=None, db=db, session_cookie=token) is None


def test_admin_without_factor_session_is_rejected(db):
    tenant = make_tenant(db)
    user = make_app_user(db, email="admin-no-mfa@example.com", tenant_id=tenant.id, role_code="admin")

    token = create_session_token(user.id, mfa_verified=False)
    assert get_optional_current_user(request=None, db=db, session_cookie=token) is None


def test_prepare_login_requires_setup_for_admin_without_factor(db):
    tenant = make_tenant(db)
    user = make_app_user(db, email="setup-required@example.com", tenant_id=tenant.id, role_code="admin")

    service = MfaService()
    current_user = build_current_user(db, user)
    pending = service.prepare_login(db, user=user, current_user=current_user, request_host="app.example.com")

    assert pending is not None
    assert pending.status == "setup_required"
    assert pending.required is True


def test_verify_login_totp_completes_pending_ticket(db):
    tenant = make_tenant(db)
    user = make_app_user(db, email="totp-login@example.com", tenant_id=tenant.id, role_code="writer")
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
    current_user = build_current_user(db, user)
    pending = service.prepare_login(db, user=user, current_user=current_user, request_host="app.example.com")
    assert pending is not None
    assert pending.status == "verification_required"

    context = service.verify_login_totp(db, ticket=pending.ticket, code=current_totp_code(secret))

    assert context.user.id == user.id
    assert context.current_user.current_tenant_id == tenant.id


def test_prepare_login_uses_saved_default_method(db):
    tenant = make_tenant(db)
    user = make_app_user(db, email="preferred-method@example.com", tenant_id=tenant.id, role_code="writer")
    user.preferred_mfa_factor_type = "totp"
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
    current_user = build_current_user(db, user)
    pending = service.prepare_login(db, user=user, current_user=current_user, request_host="app.example.com")

    assert pending is not None
    assert pending.default_factor_type == "totp"
    assert pending.default_factor_label == "Authenticator-App"


def test_set_self_preferred_method_updates_overview(db):
    tenant = make_tenant(db)
    user = make_app_user(db, email="switch-preferred@example.com", tenant_id=tenant.id, role_code="writer")
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
    actor = build_current_user(db, user, mfa_verified=True)
    overview = service.set_self_preferred_method(
        db,
        actor,
        factor_type="webauthn",
        request_host="app.example.com",
    )

    assert overview.preferred_factor_type == "webauthn"
    assert overview.preferred_factor_label == "Passkey"


def test_verify_login_totp_locks_out_account_across_tickets(db):
    """Audit finding, 2026-08-27: a fresh ticket is minted on every successful password login,
    so the pre-existing per-ticket TOTP rate limit alone let an attacker who already has valid
    credentials mint unlimited tickets and get more guesses each time. Verifies the new
    account-level ceiling (keyed by user id, not ticket) actually caps guesses across tickets."""
    tenant = make_tenant(db)
    user = make_app_user(db, email="totp-lockout@example.com", tenant_id=tenant.id, role_code="writer")
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
    current_user = build_current_user(db, user)

    for _ in range(_ACCOUNT_TOTP_ATTEMPT_LIMIT):
        pending = service.prepare_login(db, user=user, current_user=current_user, request_host="app.example.com")
        try:
            service.verify_login_totp(db, ticket=pending.ticket, code="000000")
            assert False, "expected wrong TOTP code to fail"
        except HTTPException as exc:
            assert exc.status_code == 401

    # A brand-new ticket with the *correct* code should still be blocked: the ceiling is
    # per-account, not per-ticket.
    pending = service.prepare_login(db, user=user, current_user=current_user, request_host="app.example.com")
    try:
        service.verify_login_totp(db, ticket=pending.ticket, code=current_totp_code(secret))
        assert False, "expected account-level lockout to trigger"
    except HTTPException as exc:
        assert exc.status_code == 429


def test_delete_self_factor_blocks_last_factor_for_required_user(db):
    tenant = make_tenant(db)
    user = make_app_user(db, email="required-reset@example.com", tenant_id=tenant.id, role_code="admin")
    factor = UserMfaFactor(
        user_id=user.id,
        factor_type="totp",
        label="Auth App",
        secret_encrypted=encrypt_secret(generate_totp_secret()),
    )
    db.add(factor)
    db.flush()

    service = MfaService()
    actor = build_current_user(db, user, mfa_verified=True)

    try:
        service.delete_self_factor(db, actor, factor.id)
        assert False, "expected delete_self_factor to block removing the last required factor"
    except HTTPException as exc:
        assert exc.status_code == 409


# ---- MAIN-SEC-001: Faktor-Einrichtung im Login nur ohne bestehenden Faktor ----


def _user_with_totp(db, email: str):
    tenant = make_tenant(db)
    user = make_app_user(db, email=email, tenant_id=tenant.id, role_code="writer")
    db.add(
        UserMfaFactor(
            user_id=user.id,
            factor_type="totp",
            label="Auth App",
            secret_encrypted=encrypt_secret(generate_totp_secret()),
        )
    )
    db.flush()
    return user


def test_login_enrollment_rejected_when_factor_exists(db):
    user = _user_with_totp(db, "sec001-totp@example.com")
    service = MfaService()
    pending = service.prepare_login(db, user=user, current_user=build_current_user(db, user), request_host="app.example.com")
    assert pending is not None
    assert pending.status == "verification_required"
    assert pending.can_add_totp is False
    assert pending.can_add_passkey is False

    for start in (
        lambda: service.start_login_totp_enrollment(db, pending.ticket),
        lambda: service.start_login_passkey_registration(
            db, pending.ticket, request_host="app.example.com", request_origin="https://app.example.com"
        ),
    ):
        try:
            start()
        except HTTPException as exc:
            assert exc.status_code == 403
        else:
            raise AssertionError("Einrichtung trotz bestehendem Faktor erlaubt")
    assert len(service._list_factors(db, user.id)) == 1


def test_login_enrollment_complete_rejected_when_factor_added_meanwhile(db):
    tenant = make_tenant(db)
    user = make_app_user(db, email="sec001-race@example.com", tenant_id=tenant.id, role_code="admin")
    service = MfaService()
    pending = service.prepare_login(db, user=user, current_user=build_current_user(db, user), request_host="app.example.com")
    assert pending is not None and pending.status == "setup_required"
    enrollment = service.start_login_totp_enrollment(db, pending.ticket)
    db.add(
        UserMfaFactor(
            user_id=user.id,
            factor_type="totp",
            label="Bestehend",
            secret_encrypted=encrypt_secret(generate_totp_secret()),
        )
    )
    db.flush()

    try:
        service.complete_login_totp_enrollment(
            db, flow_token=enrollment.flow_token, code=current_totp_code(enrollment.secret), label=None
        )
    except HTTPException as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("Abschluss trotz inzwischen vorhandenem Faktor erlaubt")


def test_login_enrollment_still_works_for_first_setup(db):
    tenant = make_tenant(db)
    user = make_app_user(db, email="sec001-setup@example.com", tenant_id=tenant.id, role_code="admin")
    service = MfaService()
    pending = service.prepare_login(db, user=user, current_user=build_current_user(db, user), request_host="app.example.com")
    assert pending is not None and pending.status == "setup_required"
    assert pending.can_add_totp is True

    enrollment = service.start_login_totp_enrollment(db, pending.ticket)
    context = service.complete_login_totp_enrollment(
        db, flow_token=enrollment.flow_token, code=current_totp_code(enrollment.secret), label=None
    )
    assert context.user.id == user.id
    assert len(service._list_factors(db, user.id)) == 1
