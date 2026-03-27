from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import Cookie, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.models import AppUser, Role, Tenant, UserRole, UserTenantRole


PASSWORD_SCHEME = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 390000


@dataclass
class TenantMembership:
    tenant_id: int
    tenant_name: str
    tenant_profile_image_path: str | None
    role_code: str
    is_active: bool


@dataclass
class CurrentUser:
    user_id: int
    first_name: str
    last_name: str
    display_name: str
    email: str
    preferred_language: str
    is_superadmin: bool
    current_tenant_id: int | None
    current_tenant_name: str | None
    current_tenant_profile_image_path: str | None
    current_role: str | None
    available_tenants: list[TenantMembership]

    def has_tenant_role(self, *allowed_roles: str) -> bool:
        if self.is_superadmin:
            return True
        return self.current_role in allowed_roles


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return f"{PASSWORD_SCHEME}${PASSWORD_ITERATIONS}${base64.b64encode(salt).decode()}${base64.b64encode(key).decode()}"


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


def create_session_token(user_id: int, tenant_id: int | None) -> str:
    now = datetime.now(UTC)
    payload = json.dumps(
        {
            "user_id": user_id,
            "tenant_id": tenant_id,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=settings.auth_session_ttl_hours)).timestamp()),
        },
        separators=(",", ":"),
    ).encode("utf-8")
    return _sign_payload(payload)


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
            tenant_name=tenant.name,
            tenant_profile_image_path=tenant.profile_image_path,
            role_code=role.code,
            is_active=membership.is_active,
        )
        for membership, tenant, role in rows
    ]


def build_current_user(db: Session, user: AppUser, selected_tenant_id: int | None) -> CurrentUser:
    role_codes = list(
        db.scalars(
            select(Role.code)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user.id)
        )
    )
    is_superadmin = "superadmin" in role_codes
    memberships = _load_memberships(db, user.id)
    if is_superadmin:
        all_tenants = list(db.scalars(select(Tenant).order_by(Tenant.name.asc(), Tenant.id.asc())))
        memberships = [
            TenantMembership(
                tenant_id=tenant.id,
                tenant_name=tenant.name,
                tenant_profile_image_path=tenant.profile_image_path,
                role_code="admin",
                is_active=True,
            )
            for tenant in all_tenants
        ]

    current_membership = None
    if selected_tenant_id is not None:
        current_membership = next((membership for membership in memberships if membership.tenant_id == selected_tenant_id), None)
    if current_membership is None and memberships:
        current_membership = memberships[0]
    if current_membership is None and user.default_tenant_id is not None and is_superadmin:
        tenant = db.get(Tenant, user.default_tenant_id)
        if tenant is not None:
            current_membership = TenantMembership(
                tenant_id=tenant.id,
                tenant_name=tenant.name,
                tenant_profile_image_path=tenant.profile_image_path,
                role_code="admin",
                is_active=True,
            )

    return CurrentUser(
        user_id=user.id,
        first_name=user.first_name,
        last_name=user.last_name,
        display_name=user.display_name,
        email=user.email,
        preferred_language=user.preferred_language,
        is_superadmin=is_superadmin,
        current_tenant_id=current_membership.tenant_id if current_membership else user.default_tenant_id,
        current_tenant_name=current_membership.tenant_name if current_membership else None,
        current_tenant_profile_image_path=current_membership.tenant_profile_image_path if current_membership else None,
        current_role="superadmin" if is_superadmin and current_membership is None else current_membership.role_code if current_membership else ("superadmin" if is_superadmin else None),
        available_tenants=memberships,
    )


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
    return build_current_user(db, user, session_data.get("tenant_id"))


def get_current_user(user: CurrentUser | None = Depends(get_optional_current_user)) -> CurrentUser:
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return user


def require_reader(user: CurrentUser) -> CurrentUser:
    if user.is_superadmin or user.current_role in {"reader", "writer", "admin"}:
        return user
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Reader role required")


def require_writer(user: CurrentUser) -> CurrentUser:
    if user.is_superadmin or user.current_role in {"writer", "admin"}:
        return user
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Writer role required")


def require_admin(user: CurrentUser) -> CurrentUser:
    if user.is_superadmin or user.current_role == "admin":
        return user
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")


def require_superadmin(user: CurrentUser) -> CurrentUser:
    if user.is_superadmin:
        return user
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Superadmin role required")
