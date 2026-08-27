"""Regression tests for the auth/authorization core (auth_service, access_service,
admin_auth_service) - previously zero test coverage despite being the foundation every
other tenant-isolation fix (see test_finance_tenant_scoping.py / test_fines_tenant_scoping.py)
relies on. Covers: login success/failure, password hashing (salted, both directions),
session_revoke_at invalidation, and - the most important case given the IDOR history in
this codebase - that a user's role/session in one tenant grants zero access to another
tenant's resources via AccessService."""
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException, Response

from app.core.security import (
    create_session_token,
    get_optional_current_user,
    hash_password,
    verify_password,
)
from app.schemas.user import LoginRequest
from app.services.access_service import AccessService
from app.services.admin_auth_service import AdminAuthService
from app.services.auth_service import AuthService
from app.schemas.admin import AdminLoginRequest

from tests.factories import (
    make_app_user,
    make_current_user,
    make_protocol,
    make_template,
    make_tenant,
    make_user_tenant_role,
)


# --- password hashing -------------------------------------------------------------


def test_hash_password_is_salted_same_password_different_hashes():
    hash_one = hash_password("s3cret!")
    hash_two = hash_password("s3cret!")
    assert hash_one != hash_two


def test_verify_password_round_trip():
    password_hash = hash_password("s3cret!")
    assert verify_password("s3cret!", password_hash) is True
    assert verify_password("wrong-password", password_hash) is False


def test_verify_password_rejects_malformed_hash():
    assert verify_password("anything", "not-a-valid-hash") is False


# --- AuthService.login -------------------------------------------------------------


def test_login_succeeds_with_correct_password(db):
    tenant = make_tenant(db)
    user = make_app_user(db, email="alice@example.com", password="correct-password")
    make_user_tenant_role(db, user.id, tenant.id, role_code="writer")

    service = AuthService()
    response = Response()
    session = service.login(
        db, response, LoginRequest(email="alice@example.com", password="correct-password"), request_host=None
    )

    assert session.authenticated is True
    assert session.user.email == "alice@example.com"
    assert session.current_tenant.id == tenant.public_id
    assert session.current_role == "writer"
    # A session cookie must actually be issued.
    assert any(h[0] == b"set-cookie" for h in response.raw_headers)


def test_login_fails_with_wrong_password(db):
    tenant = make_tenant(db)
    user = make_app_user(db, email="bob@example.com", password="correct-password")
    make_user_tenant_role(db, user.id, tenant.id, role_code="writer")

    service = AuthService()
    with pytest.raises(HTTPException) as exc_info:
        service.login(db, Response(), LoginRequest(email="bob@example.com", password="wrong-password"), request_host=None)
    assert exc_info.value.status_code == 401


def test_login_fails_for_unknown_email(db):
    service = AuthService()
    with pytest.raises(HTTPException) as exc_info:
        service.login(db, Response(), LoginRequest(email="nobody@example.com", password="whatever"), request_host=None)
    assert exc_info.value.status_code == 401


def test_login_fails_for_inactive_user(db):
    tenant = make_tenant(db)
    user = make_app_user(db, email="inactive@example.com", password="correct-password", is_active=False)
    make_user_tenant_role(db, user.id, tenant.id, role_code="writer")

    service = AuthService()
    with pytest.raises(HTTPException) as exc_info:
        service.login(db, Response(), LoginRequest(email="inactive@example.com", password="correct-password"), request_host=None)
    assert exc_info.value.status_code == 401


def test_login_fails_without_any_tenant_membership(db):
    make_app_user(db, email="orphan@example.com", password="correct-password")

    service = AuthService()
    with pytest.raises(HTTPException) as exc_info:
        service.login(db, Response(), LoginRequest(email="orphan@example.com", password="correct-password"), request_host=None)
    assert exc_info.value.status_code == 403


# --- session_revoke_at --------------------------------------------------------------


def test_session_token_issued_before_revoke_at_is_rejected(db):
    tenant = make_tenant(db)
    user = make_app_user(db, email="carol@example.com", password="correct-password")
    make_user_tenant_role(db, user.id, tenant.id, role_code="writer")

    # Mint a token, then simulate a later logout-everywhere by moving session_revoke_at
    # to *after* the token's issued-at timestamp.
    token = create_session_token(user.id, tenant.id)
    user.session_revoke_at = datetime.now(UTC) + timedelta(seconds=5)
    db.add(user)
    db.flush()

    result = get_optional_current_user(request=None, db=db, session_cookie=token)
    assert result is None


def test_session_token_issued_after_revoke_at_is_accepted(db):
    tenant = make_tenant(db)
    user = make_app_user(db, email="dave@example.com", password="correct-password")
    make_user_tenant_role(db, user.id, tenant.id, role_code="writer")

    # revoke_at in the past - a freshly issued token (iat "now") must still be valid.
    user.session_revoke_at = datetime.now(UTC) - timedelta(hours=1)
    db.add(user)
    db.flush()

    token = create_session_token(user.id, tenant.id)
    result = get_optional_current_user(request=None, db=db, session_cookie=token)
    assert result is not None
    assert result.user_id == user.id


def test_get_optional_current_user_rejects_tampered_token(db):
    tenant = make_tenant(db)
    user = make_app_user(db, email="erin@example.com", password="correct-password")
    make_user_tenant_role(db, user.id, tenant.id, role_code="writer")

    token = create_session_token(user.id, tenant.id)
    tampered = token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")
    result = get_optional_current_user(request=None, db=db, session_cookie=tampered)
    assert result is None


def test_session_is_rejected_after_last_tenant_membership_is_deactivated(db):
    tenant = make_tenant(db)
    user = make_app_user(db, email="former-member@example.com", password="correct-password")
    membership = make_user_tenant_role(db, user.id, tenant.id, role_code="reader")
    token = create_session_token(user.id, tenant.id)

    membership.is_active = False
    db.add(membership)
    db.flush()

    # The cookie is still correctly signed, but without an active tenant/role it must not
    # produce an authenticated session that sends the frontend into 403-only pages.
    assert get_optional_current_user(request=None, db=db, session_cookie=token) is None


# --- AccessService: cross-tenant isolation (the core IDOR-class check) -------------


def test_writer_cannot_read_protocol_of_another_tenant(db):
    service = AccessService()
    tenant_a = make_tenant(db, "Tenant A")
    tenant_b = make_tenant(db, "Tenant B")
    template_b = make_template(db, tenant_b.id)
    protocol_b = make_protocol(db, tenant_b.id, template_b.id)

    user_in_tenant_a = make_current_user(tenant_a.id, role="writer")

    assert service.can_read_protocol(db, user_in_tenant_a, protocol_b.id) is False
    with pytest.raises(HTTPException) as exc_info:
        service.ensure_can_read_protocol(db, user_in_tenant_a, protocol_b.id)
    assert exc_info.value.status_code == 403


def test_admin_cannot_read_template_of_another_tenant(db):
    service = AccessService()
    tenant_a = make_tenant(db, "Tenant A")
    tenant_b = make_tenant(db, "Tenant B")
    template_b = make_template(db, tenant_b.id)

    admin_in_tenant_a = make_current_user(tenant_a.id, role="admin")

    assert service.can_read_template(db, admin_in_tenant_a, template_b.id) is False


def test_writer_can_read_protocol_of_own_tenant(db):
    service = AccessService()
    tenant_a = make_tenant(db, "Tenant A")
    template_a = make_template(db, tenant_a.id)
    protocol_a = make_protocol(db, tenant_a.id, template_a.id)

    user_in_tenant_a = make_current_user(tenant_a.id, role="writer")

    assert service.can_read_protocol(db, user_in_tenant_a, protocol_a.id) is True
    # Should not raise.
    service.ensure_can_read_protocol(db, user_in_tenant_a, protocol_a.id)


def test_unrestricted_reader_cannot_read_protocol_of_another_tenant(db):
    """A plain reader (no scoped access rows at all) falls back to "any protocol in their
    own tenant" per _is_restricted_reader - but must still never reach another tenant."""
    service = AccessService()
    tenant_a = make_tenant(db, "Tenant A")
    tenant_b = make_tenant(db, "Tenant B")
    template_b = make_template(db, tenant_b.id)
    protocol_b = make_protocol(db, tenant_b.id, template_b.id)

    reader_in_tenant_a = make_current_user(tenant_a.id, role="reader")

    assert service.can_read_protocol(db, reader_in_tenant_a, protocol_b.id) is False


def test_unrestricted_reader_cannot_read_template_of_another_tenant(db):
    """Same gap as above, for can_read_template's unrestricted-reader fallback."""
    service = AccessService()
    tenant_a = make_tenant(db, "Tenant A")
    tenant_b = make_tenant(db, "Tenant B")
    template_b = make_template(db, tenant_b.id)

    reader_in_tenant_a = make_current_user(tenant_a.id, role="reader")

    assert service.can_read_template(db, reader_in_tenant_a, template_b.id) is False


def test_unrestricted_reader_can_read_protocol_of_own_tenant(db):
    """The fix must not regress the legitimate case: an unrestricted reader still has full
    read access within their own tenant."""
    service = AccessService()
    tenant_a = make_tenant(db, "Tenant A")
    template_a = make_template(db, tenant_a.id)
    protocol_a = make_protocol(db, tenant_a.id, template_a.id)

    reader_in_tenant_a = make_current_user(tenant_a.id, role="reader")

    assert service.can_read_protocol(db, reader_in_tenant_a, protocol_a.id) is True


def test_get_optional_current_admin_rejects_token_without_mfa_claim(db):
    """Audit finding, 2026-08-27: every admin session token must now carry an explicit,
    truthy "mfa" claim - a token minted before this fix (or hand-crafted without it) must be
    rejected outright rather than silently treated as valid, even though its signature and
    admin_id/iat/exp are otherwise perfectly well-formed."""
    import json

    from app.core.admin_security import _sign_payload, get_optional_current_admin
    from app.models.entities import PlatformAdmin

    admin = PlatformAdmin(
        email="ops-legacy-token@example.com",
        password_hash=hash_password("admin-password"),
        display_name="Ops",
    )
    db.add(admin)
    db.flush()

    now = int(datetime.now(UTC).timestamp())
    legacy_payload = json.dumps(
        {"admin_id": admin.id, "iat": now, "exp": now + 3600}, separators=(",", ":")
    ).encode()
    legacy_token = _sign_payload(legacy_payload)
    assert get_optional_current_admin(request=None, db=db, session_cookie=legacy_token) is None

    explicit_false_payload = json.dumps(
        {"admin_id": admin.id, "mfa": False, "iat": now, "exp": now + 3600}, separators=(",", ":")
    ).encode()
    explicit_false_token = _sign_payload(explicit_false_payload)
    assert get_optional_current_admin(request=None, db=db, session_cookie=explicit_false_token) is None


# --- GET /api/auth/tenant-by-domain: public, but rate-limited -----------------------


class _FakeClient:
    def __init__(self, host: str) -> None:
        self.host = host


class _FakeRequest:
    """Duck-typed stand-in for fastapi.Request - the route only ever touches .headers.get(...)
    and .client.host (see auth.py's _client_ip), so a real Starlette Request/ASGI scope isn't
    needed here, matching this repo's existing "call the route as a plain callable" convention
    (see test_audit_2026_08_12_high_fixes_H.py)."""

    def __init__(self, *, host: str, forwarded_for: str | None = None) -> None:
        self.client = _FakeClient(host)
        self.headers = {"x-forwarded-for": forwarded_for} if forwarded_for else {}


def test_tenant_by_domain_rate_limited_per_source_ip(db):
    """Audit finding, 2026-08-27: GET /api/auth/tenant-by-domain is deliberately unauthenticated
    (used pre-login) but had no rate limit at all, making it a free domain-enumeration oracle.
    A fresh, distinctive fake IP is used per test run to avoid colliding with any other test's
    rate-limit bucket in the shared Redis instance the `db` fixture doesn't reset."""
    from app.api.routes.auth import tenant_by_domain

    fake_ip = f"198.51.100.{uuid.uuid4().hex[:6]}"
    request = _FakeRequest(host=fake_ip)

    for _ in range(20):
        with pytest.raises(HTTPException) as exc_info:
            tenant_by_domain("no-such-domain.example.com", request, db)
        assert exc_info.value.status_code == 404

    # The 21st request from the same source within the window must be rejected outright,
    # before ever reaching the (still-nonexistent) domain lookup.
    with pytest.raises(HTTPException) as exc_info:
        tenant_by_domain("no-such-domain.example.com", request, db)
    assert exc_info.value.status_code == 429


def test_tenant_by_domain_client_ip_prefers_x_forwarded_for(db):
    """_client_ip must read the real client IP from X-Forwarded-For (set by Traefik) rather
    than request.client.host, which would just be Traefik's own container IP - otherwise every
    request through the proxy shares a single rate-limit bucket."""
    from app.api.routes.auth import _client_ip

    real_client_ip = f"198.51.100.{uuid.uuid4().hex[:6]}"
    request = _FakeRequest(host="10.0.0.5", forwarded_for=f"{real_client_ip}, 10.0.0.5")
    assert _client_ip(request) == real_client_ip


# --- AdminAuthService ----------------------------------------------------------------


def test_admin_login_succeeds_with_correct_password_but_requires_mfa_setup(db):
    """Audit finding, 2026-08-27: platform admins previously got a full session straight off
    a correct password. Now login() always returns a pending MFA ticket - here, "setup_required"
    since this admin has no TOTP factor yet - and only completing enrollment through the
    ticket-based flow (mirroring the tenant-admin flow in mfa_service.py) actually grants a
    session."""
    from app.core.totp import current_totp_code
    from app.models.entities import PlatformAdmin
    from app.schemas.mfa import MfaTicketRequest, TotpEnrollmentComplete

    admin = PlatformAdmin(
        email="ops@example.com",
        password_hash=hash_password("admin-password"),
        display_name="Ops",
    )
    db.add(admin)
    db.flush()

    service = AdminAuthService()
    pending = service.login(db, Response(), AdminLoginRequest(email="ops@example.com", password="admin-password"))
    assert pending.authenticated is False
    assert pending.admin is None
    assert pending.mfa is not None
    assert pending.mfa.status == "setup_required"
    assert pending.mfa.required is True

    enrollment = service.start_login_totp_setup(db, MfaTicketRequest(ticket=pending.mfa.ticket))
    code = current_totp_code(enrollment.secret)
    session = service.complete_login_totp_setup(
        db, Response(), TotpEnrollmentComplete(flow_token=enrollment.flow_token, code=code)
    )
    assert session.authenticated is True
    assert session.admin.email == "ops@example.com"
    assert session.mfa is None


def test_admin_login_with_existing_totp_factor_requires_verification(db):
    """Once a factor exists, login() returns "verification_required" instead of
    "setup_required" - the account-level TOTP lockout (see admin_mfa_service.py, mirroring
    mfa_service.py's identical fix) is exercised in test_admin_mfa_service.py."""
    from app.core.secret_crypto import encrypt_secret
    from app.core.totp import current_totp_code, generate_totp_secret
    from app.models.entities import PlatformAdmin, UserMfaFactor
    from app.schemas.mfa import TotpLoginVerifyRequest

    secret = generate_totp_secret()
    admin = PlatformAdmin(
        email="ops-with-totp@example.com",
        password_hash=hash_password("admin-password"),
        display_name="Ops",
    )
    db.add(admin)
    db.flush()
    db.add(
        UserMfaFactor(
            platform_admin_id=admin.id,
            factor_type="totp",
            label="Auth App",
            secret_encrypted=encrypt_secret(secret),
        )
    )
    db.flush()

    service = AdminAuthService()
    pending = service.login(db, Response(), AdminLoginRequest(email="ops-with-totp@example.com", password="admin-password"))
    assert pending.mfa.status == "verification_required"

    session = service.verify_login_totp(
        db, Response(), TotpLoginVerifyRequest(ticket=pending.mfa.ticket, code=current_totp_code(secret))
    )
    assert session.authenticated is True
    assert session.admin.email == "ops-with-totp@example.com"


def test_admin_login_fails_with_wrong_password(db):
    from app.models.entities import PlatformAdmin

    admin = PlatformAdmin(
        email="ops2@example.com",
        password_hash=hash_password("admin-password"),
        display_name="Ops",
    )
    db.add(admin)
    db.flush()

    service = AdminAuthService()
    with pytest.raises(HTTPException) as exc_info:
        service.login(db, Response(), AdminLoginRequest(email="ops2@example.com", password="wrong"))
    assert exc_info.value.status_code == 401


def test_admin_logout_revokes_existing_session_tokens(db):
    import json

    from app.core.admin_security import CurrentAdmin, _sign_payload, get_optional_current_admin
    from app.models.entities import PlatformAdmin

    admin = PlatformAdmin(
        email="ops3@example.com",
        password_hash=hash_password("admin-password"),
        display_name="Ops",
    )
    db.add(admin)
    db.flush()

    # Forge a token with an iat a few seconds in the past (rather than using
    # create_admin_session_token, which stamps "now") so it can't land in the same
    # truncated-to-the-second bucket as the session_revoke_at logout() is about to set -
    # get_optional_current_admin's revocation check compares int() timestamps, so a same-second
    # iat/revoke_at pair would flakily look "not yet revoked" regardless of the fix.
    past_iat = int((datetime.now(UTC) - timedelta(seconds=30)).timestamp())
    payload = json.dumps(
        {"admin_id": admin.id, "mfa": True, "iat": past_iat, "exp": past_iat + 3600}, separators=(",", ":")
    ).encode()
    token = _sign_payload(payload)
    assert get_optional_current_admin(request=None, db=db, session_cookie=token) is not None

    # A token minted before logout must stop working afterwards - logout must not just
    # clear the cookie, it must bump session_revoke_at like customer logout / deactivation do.
    service = AdminAuthService()
    service.logout(
        db, Response(), CurrentAdmin(admin_id=admin.id, admin_public_id=admin.public_id, email=admin.email, display_name=admin.display_name)
    )

    assert admin.session_revoke_at is not None
    assert get_optional_current_admin(request=None, db=db, session_cookie=token) is None
