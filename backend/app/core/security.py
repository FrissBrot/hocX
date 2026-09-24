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
from app.models import AppUser, Role, Tenant, TenantFeature, UserMfaFactor


PASSWORD_SCHEME = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 600000


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
    # A user belongs to exactly one tenant with exactly one role (app_user.tenant_id/role_id);
    # the "current_" prefix is historical from when a session could switch between tenants.
    current_tenant_id: int
    current_tenant_public_id: uuid.UUID
    current_tenant_name: str
    current_tenant_profile_image_path: str | None
    current_role: str
    protocol_accordion_enabled: bool = True
    mfa_verified: bool = False
    # Feature-Gating pro Mandant (orthogonal zur Rolle): welche Features fuer
    # current_tenant_id gebucht sind. Leer per Default (deny-by-default) - build_current_user
    # laedt den echten Stand aus tenant_feature.
    current_tenant_features: frozenset[str] = frozenset()

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


def create_session_token(user_id: int, *, mfa_verified: bool = False) -> str:
    now = datetime.now(UTC)
    payload = json.dumps(
        {
            "user_id": user_id,
            "mfa": bool(mfa_verified),
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=settings.auth_session_ttl_hours)).timestamp()),
        },
        separators=(",", ":"),
    ).encode("utf-8")
    return _sign_payload(payload)


def issue_session_cookie(response: Response, user_id: int, *, mfa_verified: bool = False) -> None:
    """Mints a fresh session token and sets it as a host-only cookie on the response - shared by
    login and the cross-domain login bridge so both stay consistent. (OIDC is admin-panel-only
    now - see platform_oidc_service.py / issue_admin_session_cookie.) Sessions issued before
    the single-tenant switch carry an extra "tenant_id" claim, which parse_session_token simply
    ignores."""
    token = create_session_token(user_id, mfa_verified=mfa_verified)
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


def build_current_user(db: Session, user: AppUser, *, mfa_verified: bool = False) -> CurrentUser:
    tenant, role = db.execute(
        select(Tenant, Role).where(Tenant.id == user.tenant_id, Role.id == user.role_id)
    ).one()
    tenant_features = frozenset(
        db.scalars(select(TenantFeature.feature_code).where(TenantFeature.tenant_id == tenant.id))
    )
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
        current_tenant_id=tenant.id,
        current_tenant_public_id=tenant.public_id,
        current_tenant_name=tenant.name,
        current_tenant_profile_image_path=tenant.profile_image_path,
        current_role=role.code,
        mfa_verified=mfa_verified,
        current_tenant_features=tenant_features,
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
    return user.current_role == "admin"


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
    current_user = build_current_user(db, user, mfa_verified=bool(session_data.get("mfa")))
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


def require_feature(user: CurrentUser, code: str) -> CurrentUser:
    """Feature-Gating pro Mandant - orthogonal zur Rollenpruefung. Ein 403 hier bedeutet "fuer
    diesen Mandanten nicht gebucht", nicht "diese Rolle darf das nicht"."""
    if code not in user.current_tenant_features:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Feature '{code}' nicht gebucht")
    return user


def require_finance_read(user: CurrentUser) -> CurrentUser:
    """Every tenant role may inspect finance data, if the tenant has Finanzen booked."""
    require_feature(user, "finance")
    if user.current_role in {"reader", "kassier", "writer", "admin"}:
        return user
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Finance read access required")


def require_finance_write(user: CurrentUser) -> CurrentUser:
    """Only the dedicated cashier role and tenant admins may mutate finance data, if the tenant
    has Finanzen booked."""
    require_feature(user, "finance")
    if user.current_role in {"kassier", "admin"}:
        return user
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Finance write access required")


def require_abgabebox_read(user: CurrentUser) -> CurrentUser:
    """Every tenant role may inspect Abgabebox data, if the tenant has Abgabebox booked."""
    require_feature(user, "abgabebox")
    if user.current_role in {"reader", "kassier", "writer", "admin"}:
        return user
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Abgabebox read access required")


def require_abgabebox_write(user: CurrentUser) -> CurrentUser:
    """Only writer/admin may manage Abgaben, if the tenant has Abgabebox booked."""
    require_feature(user, "abgabebox")
    if user.current_role in {"writer", "admin"}:
        return user
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Abgabebox write access required")


def require_all_fines_read(user: CurrentUser) -> CurrentUser:
    """Reader accounts may only use the self-scoped fines listing."""
    if user.current_role in {"writer", "kassier", "admin"}:
        return user
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="All-fines read access required")


def require_admin(user: CurrentUser) -> CurrentUser:
    if user.current_role == "admin":
        return user
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
