from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.models import AppUser, Role, Tenant, UserMfaFactor, UserTenantRole
from app.services import public_id_service


PASSWORD_SCHEME = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 600000


@dataclass
class TenantMembership:
    tenant_id: int
    tenant_public_id: uuid.UUID
    tenant_name: str
    tenant_profile_image_path: str | None
    role_code: str
    is_active: bool


@dataclass
class CurrentUser:
    user_id: int
    user_public_id: uuid.UUID
    first_name: str
    last_name: str
    display_name: str
    email: str
    preferred_language: str
    is_participant_account: bool
    default_tenant_id: int | None
    default_tenant_public_id: uuid.UUID | None
    current_tenant_id: int | None
    current_tenant_public_id: uuid.UUID | None
    current_tenant_name: str | None
    current_tenant_profile_image_path: str | None
    current_role: str | None
    available_tenants: list[TenantMembership]
    protocol_accordion_enabled: bool = True
    mfa_verified: bool = False

    def has_tenant_role(self, *allowed_roles: str) -> bool:
        return self.current_role in allowed_roles


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return f"{PASSWORD_SCHEME}${PASSWORD_ITERATIONS}${base64.b64encode(salt).decode()}${base64.b64encode(key).decode()}"


# A fixed, valid-shaped hash with no corresponding real password - used to run
# verify_password's full PBKDF2 work even when no account exists, so a login attempt
# against an unknown email takes the same time as one against a real email with a wrong
# password (audit finding, 2026-08-25: short-circuiting straight past verify_password for
# a missing account was a measurable, account-enumerating timing side channel).
DUMMY_PASSWORD_HASH = hash_password("hocx-dummy-password-for-timing-only")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        scheme, iterations_raw, salt_raw, digest_raw = password_hash.split("$", 3)
        if scheme != PASSWORD_SCHEME:
            return False
        iterations = int(iterations_raw)
        salt = base64.b64decode(salt_raw.encode("utf-8"))
        expected = base64.b64decode(digest_raw.encode("utf-8"))
    except (ValueError, TypeError):
        return False

    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def _sign_payload(payload: bytes) -> str:
    signature = hmac.new(settings.auth_secret.encode("utf-8"), payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(payload).decode("utf-8") + "." + base64.urlsafe_b64encode(signature).decode("utf-8")


def create_session_token(user_id: int, tenant_id: int | None, *, mfa_verified: bool = False) -> str:
    now = datetime.now(UTC)
    payload = json.dumps(
        {
            "user_id": user_id,
            "tenant_id": tenant_id,
            "mfa": bool(mfa_verified),
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=settings.auth_session_ttl_hours)).timestamp()),
        },
        separators=(",", ":"),
    ).encode("utf-8")
    return _sign_payload(payload)


def issue_session_cookie(response: Response, user_id: int, tenant_id: int | None, *, mfa_verified: bool = False) -> None:
    """Mints a fresh session token and sets it as a host-only cookie on the response - shared by
    login, select-tenant and the cross-domain login bridge so all three stay consistent. (OIDC
    is admin-panel-only now - see platform_oidc_service.py / issue_admin_session_cookie.)"""
    token = create_session_token(user_id, tenant_id, mfa_verified=mfa_verified)
    response.set_cookie(
        key=settings.auth_session_cookie,
        value=token,
        httponly=True,
        secure=settings.auth_secure_cookies,
        samesite="lax",
        max_age=settings.auth_session_ttl_hours * 3600,
        path="/",
    )


def parse_session_token(token: str | None) -> dict | None:
    if not token or "." not in token:
        return None
    token = token.strip('"')
    payload_b64, signature_b64 = token.split(".", 1)
    try:
        payload = base64.urlsafe_b64decode(payload_b64.encode("utf-8"))
        expected = hmac.new(settings.auth_secret.encode("utf-8"), payload, hashlib.sha256).digest()
        provided = base64.urlsafe_b64decode(signature_b64.encode("utf-8"))
    except (ValueError, TypeError):
        return None
    if not hmac.compare_digest(expected, provided):
        return None
    try:
        data = json.loads(payload.decode("utf-8"))
    except json.JSONDecodeError:
        return None
    if int(data.get("exp", 0)) < int(datetime.now(UTC).timestamp()):
        return None
    return data


def _load_memberships(db: Session, user_id: int) -> list[TenantMembership]:
    rows = db.execute(
        select(UserTenantRole, Tenant, Role)
        .join(Tenant, Tenant.id == UserTenantRole.tenant_id)
        .join(Role, Role.id == UserTenantRole.role_id)
        .where(UserTenantRole.user_id == user_id, UserTenantRole.is_active.is_(True))
        .order_by(Tenant.name.asc(), Tenant.id.asc())
    ).all()
    return [
        TenantMembership(
            tenant_id=tenant.id,
            tenant_public_id=tenant.public_id,
            tenant_name=tenant.name,
            tenant_profile_image_path=tenant.profile_image_path,
            role_code=role.code,
            is_active=membership.is_active,
        )
        for membership, tenant, role in rows
    ]


def build_current_user(db: Session, user: AppUser, selected_tenant_id: int | None, *, mfa_verified: bool = False) -> CurrentUser:
    memberships = _load_memberships(db, user.id)

    current_membership = None
    if selected_tenant_id is not None:
        current_membership = next((membership for membership in memberships if membership.tenant_id == selected_tenant_id), None)
    if current_membership is None and user.default_tenant_id is not None:
        current_membership = next((membership for membership in memberships if membership.tenant_id == user.default_tenant_id), None)
    if current_membership is None and memberships:
        current_membership = memberships[0]

    default_tenant_public_id = None
    if user.default_tenant_id is not None:
        default_tenant_public_id = next(
            (m.tenant_public_id for m in memberships if m.tenant_id == user.default_tenant_id),
            None,
        ) or public_id_service.resolve_public_id(db, Tenant, user.default_tenant_id)

    return CurrentUser(
        user_id=user.id,
        user_public_id=user.public_id,
        first_name=user.first_name,
        last_name=user.last_name,
        display_name=user.display_name,
        email=user.email,
        preferred_language=user.preferred_language,
        protocol_accordion_enabled=(user.external_identity_json or {}).get("protocol_accordion_enabled", True) is not False,
        is_participant_account=(user.external_identity_json or {}).get("source") == "participant_auto",
        default_tenant_id=user.default_tenant_id,
        default_tenant_public_id=default_tenant_public_id,
        # current_membership is only ever None here if the user has zero active tenant
        # roles at all (a matching default_tenant_id membership, if active, was already
        # picked up above) - falling back to the possibly-stale default_tenant_id in that
        # case let login() succeed with a non-None current_tenant_id and an empty
        # current_role, a "phantom tenant" state that only every endpoint's separate
        # current_role check happens to make harmless today (audit finding, 2026-08-25).
        current_tenant_id=current_membership.tenant_id if current_membership else None,
        current_tenant_public_id=current_membership.tenant_public_id if current_membership else None,
        current_tenant_name=current_membership.tenant_name if current_membership else None,
        current_tenant_profile_image_path=current_membership.tenant_profile_image_path if current_membership else None,
        current_role=current_membership.role_code if current_membership else None,
        available_tenants=memberships,
        mfa_verified=mfa_verified,
    )


def _has_active_mfa_factor(db: Session, user_id: int) -> bool:
    return (
        db.query(UserMfaFactor.id)
        .filter(UserMfaFactor.user_id == user_id)
        .limit(1)
        .one_or_none()
        is not None
    )


def _requires_mfa(user: CurrentUser) -> bool:
    return any(membership.role_code == "admin" and membership.is_active for membership in user.available_tenants)


def get_optional_current_user(
    request: Request,
    db: Session = Depends(get_db),
    session_cookie: str | None = Cookie(default=None, alias=settings.auth_session_cookie),
) -> CurrentUser | None:
    token = session_cookie or request.cookies.get(settings.auth_session_cookie)
    session_data = parse_session_token(token)
    if session_data is None:
        return None
    user = db.get(AppUser, int(session_data["user_id"]))
    if user is None or not user.is_active:
        return None
    if user.session_revoke_at is not None:
        token_iat = int(session_data.get("iat", 0))
        if int(user.session_revoke_at.timestamp()) > token_iat:
            return None
    current_user = build_current_user(db, user, session_data.get("tenant_id"), mfa_verified=bool(session_data.get("mfa")))
    has_mfa_factor = _has_active_mfa_factor(db, user.id)
    if has_mfa_factor and not current_user.mfa_verified:
        return None
    if _requires_mfa(current_user) and (not has_mfa_factor or not current_user.mfa_verified):
        return None
    return current_user


def get_current_user(user: CurrentUser | None = Depends(get_optional_current_user)) -> CurrentUser:
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return user


def require_reader(user: CurrentUser) -> CurrentUser:
    if user.current_role in {"reader", "kassier", "writer", "admin"}:
        return user
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Reader role required")


def require_writer(user: CurrentUser) -> CurrentUser:
    if user.current_role in {"writer", "admin"}:
        return user
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Writer role required")


def require_finance_read(user: CurrentUser) -> CurrentUser:
    """Every tenant role may inspect finance data."""
    if user.current_role in {"reader", "kassier", "writer", "admin"}:
        return user
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Finance read access required")


def require_finance_write(user: CurrentUser) -> CurrentUser:
    """Only the dedicated cashier role and tenant admins may mutate finance data."""
    if user.current_role in {"kassier", "admin"}:
        return user
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Finance write access required")


def require_all_fines_read(user: CurrentUser) -> CurrentUser:
    """Reader accounts may only use the self-scoped fines listing."""
    if user.current_role in {"writer", "kassier", "admin"}:
        return user
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="All-fines read access required")


def require_admin(user: CurrentUser) -> CurrentUser:
    if user.current_role == "admin":
        return user
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
