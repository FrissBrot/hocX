"""Regression tests for AdminMfaService (audit finding, 2026-08-27 - platform admins, the
highest-privilege tier in this system, previously had no MFA option at all, unlike tenant
admins - see mfa_service.py / test_mfa_service.py, which this file's structure mirrors).
Covers: self-service enrollment/overview/deletion for an already-authenticated admin, the
login-ticket flow (setup_required vs verification_required), and the account-level TOTP
lockout that stops multi-ticket brute-force (built in from the start here, unlike the
tenant-user equivalent this same audit round retrofitted - see test_mfa_service.py's
test_verify_login_totp_locks_out_account_across_tickets)."""
from __future__ import annotations

from fastapi import HTTPException

from app.core.admin_security import CurrentAdmin
from app.core.secret_crypto import encrypt_secret
from app.core.totp import current_totp_code, generate_totp_secret
from app.models.entities import PlatformAdmin, UserMfaFactor
from app.services.admin_mfa_service import _ACCOUNT_TOTP_ATTEMPT_LIMIT, AdminMfaService


def _make_admin(db, email: str) -> PlatformAdmin:
    from app.core.security import hash_password

    admin = PlatformAdmin(email=email, password_hash=hash_password("admin-password"), display_name="Ops")
    db.add(admin)
    db.flush()
    return admin


def _actor_for(admin: PlatformAdmin) -> CurrentAdmin:
    return CurrentAdmin(
        admin_id=admin.id, admin_public_id=admin.public_id, email=admin.email, display_name=admin.display_name
    )


def test_prepare_login_requires_setup_when_no_factor_exists(db):
    admin = _make_admin(db, "admin-no-factor@example.com")
    service = AdminMfaService()

    pending = service.prepare_login(db, admin)

    assert pending.status == "setup_required"
    assert pending.required is True
    assert pending.can_add_passkey is False


def test_prepare_login_requires_verification_when_factor_exists(db):
    admin = _make_admin(db, "admin-with-factor@example.com")
    db.add(
        UserMfaFactor(
            platform_admin_id=admin.id,
            factor_type="totp",
            label="Auth App",
            secret_encrypted=encrypt_secret(generate_totp_secret()),
        )
    )
    db.flush()
    service = AdminMfaService()

    pending = service.prepare_login(db, admin)
    assert pending.status == "verification_required"
    assert pending.default_factor_type == "totp"


def test_login_ticket_totp_enrollment_completes_and_grants_pending_login_context(db):
    admin = _make_admin(db, "admin-enroll@example.com")
    service = AdminMfaService()

    pending = service.prepare_login(db, admin)
    assert pending.status == "setup_required"

    enrollment = service.start_login_totp_enrollment(db, pending.ticket)
    code = current_totp_code(enrollment.secret)
    context = service.complete_login_totp_enrollment(db, flow_token=enrollment.flow_token, code=code, label=None)

    assert context.admin.id == admin.id
    factors = service._list_factors(db, admin.id)
    assert len(factors) == 1
    assert factors[0].factor_type == "totp"
    assert factors[0].user_id is None
    assert factors[0].platform_admin_id == admin.id


def test_verify_login_totp_completes_pending_ticket(db):
    admin = _make_admin(db, "admin-verify@example.com")
    secret = generate_totp_secret()
    db.add(
        UserMfaFactor(
            platform_admin_id=admin.id,
            factor_type="totp",
            label="Auth App",
            secret_encrypted=encrypt_secret(secret),
        )
    )
    db.flush()
    service = AdminMfaService()

    pending = service.prepare_login(db, admin)
    context = service.verify_login_totp(db, ticket=pending.ticket, code=current_totp_code(secret))
    assert context.admin.id == admin.id


def test_verify_login_totp_locks_out_account_across_tickets(db):
    """Mirrors mfa_service.py's identical fix for tenant-user TOTP login: a fresh ticket is
    mintable on every successful password login, so a per-ticket-only limit lets an attacker
    who already has valid credentials mint unlimited tickets for more guesses each time. The
    account-level ceiling here is keyed by admin id, not ticket."""
    admin = _make_admin(db, "admin-lockout@example.com")
    secret = generate_totp_secret()
    db.add(
        UserMfaFactor(
            platform_admin_id=admin.id,
            factor_type="totp",
            label="Auth App",
            secret_encrypted=encrypt_secret(secret),
        )
    )
    db.flush()
    service = AdminMfaService()

    for _ in range(_ACCOUNT_TOTP_ATTEMPT_LIMIT):
        pending = service.prepare_login(db, admin)
        try:
            service.verify_login_totp(db, ticket=pending.ticket, code="000000")
            assert False, "expected wrong TOTP code to fail"
        except HTTPException as exc:
            assert exc.status_code == 401

    pending = service.prepare_login(db, admin)
    try:
        service.verify_login_totp(db, ticket=pending.ticket, code=current_totp_code(secret))
        assert False, "expected account-level lockout to trigger"
    except HTTPException as exc:
        assert exc.status_code == 429


def test_self_service_totp_enrollment_and_overview(db):
    admin = _make_admin(db, "admin-self-service@example.com")
    actor = _actor_for(admin)
    service = AdminMfaService()

    overview_before = service.get_self_overview(db, actor)
    assert overview_before.required is True
    assert overview_before.has_factors is False

    enrollment = service.start_self_totp_enrollment(db, actor)
    code = current_totp_code(enrollment.secret)
    service.complete_self_totp_enrollment(db, actor, flow_token=enrollment.flow_token, code=code, label="My Phone")

    overview_after = service.get_self_overview(db, actor)
    assert overview_after.has_factors is True
    assert overview_after.factors[0].label == "My Phone"


def test_delete_self_factor_blocks_removing_last_factor(db):
    """Every platform admin requires MFA unconditionally - unlike tenant users, where this
    guard only applies to admin-role members (see mfa_service.py's identical check)."""
    admin = _make_admin(db, "admin-last-factor@example.com")
    actor = _actor_for(admin)
    factor = UserMfaFactor(
        platform_admin_id=admin.id,
        factor_type="totp",
        label="Auth App",
        secret_encrypted=encrypt_secret(generate_totp_secret()),
    )
    db.add(factor)
    db.flush()
    service = AdminMfaService()

    try:
        service.delete_self_factor(db, actor, factor.id)
        assert False, "expected delete_self_factor to block removing the last factor"
    except HTTPException as exc:
        assert exc.status_code == 409


def test_delete_self_factor_unknown_id_returns_404(db):
    admin = _make_admin(db, "admin-unknown-factor@example.com")
    actor = _actor_for(admin)
    service = AdminMfaService()

    try:
        service.delete_self_factor(db, actor, 999999999)
        assert False, "expected 404 for an unknown factor id"
    except HTTPException as exc:
        assert exc.status_code == 404


def test_factor_scoped_to_owning_admin_not_visible_to_another_admin(db):
    """UserMfaFactor rows are now shared between AppUser and PlatformAdmin owners (via the
    new platform_admin_id column) - _list_factors/_get_factor must stay strictly scoped to
    the requesting admin's own id."""
    admin_one = _make_admin(db, "admin-scope-one@example.com")
    admin_two = _make_admin(db, "admin-scope-two@example.com")
    db.add(
        UserMfaFactor(
            platform_admin_id=admin_one.id,
            factor_type="totp",
            label="Admin One's App",
            secret_encrypted=encrypt_secret(generate_totp_secret()),
        )
    )
    db.flush()
    service = AdminMfaService()

    assert service.get_self_overview(db, _actor_for(admin_two)).has_factors is False
    assert service.get_self_overview(db, _actor_for(admin_one)).has_factors is True
