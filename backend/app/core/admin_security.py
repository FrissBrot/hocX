from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.security import verify_password  # noqa: F401  (re-exported for convenience)
from app.models import PlatformAdmin

"""Auth for the platform-admin panel. Deliberately independent from app.core.security:
own cookie, own signing secret, own principal type (PlatformAdmin, not AppUser) - a leaked
or forged token for one system must never be valid for the other."""


@dataclass
class CurrentAdmin:
    admin_id: int
    email: str
    display_name: str
    role: str = "owner"


def _sign_payload(payload: bytes) -> str:
    signature = hmac.new(settings.admin_auth_secret.encode("utf-8"), payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(payload).decode("utf-8") + "." + base64.urlsafe_b64encode(signature).decode("utf-8")


def create_admin_session_token(admin_id: int) -> str:
    now = datetime.now(UTC)
    payload = json.dumps(
        {
            "admin_id": admin_id,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=settings.admin_session_ttl_hours)).timestamp()),
        },
        separators=(",", ":"),
    ).encode("utf-8")
    return _sign_payload(payload)


def issue_admin_session_cookie(response: Response, admin_id: int) -> None:
    """Mints a fresh admin session token and sets it as a host-only cookie - shared by password
    login and the SSO callback so both stay consistent."""
    token = create_admin_session_token(admin_id)
    response.set_cookie(
        key=settings.admin_session_cookie,
        value=token,
        httponly=True,
        secure=settings.auth_secure_cookies,
        samesite="lax",
        max_age=settings.admin_session_ttl_hours * 3600,
        path="/",
    )


def parse_admin_session_token(token: str | None) -> dict | None:
    if not token or "." not in token:
        return None
    token = token.strip('"')
    payload_b64, signature_b64 = token.split(".", 1)
    try:
        payload = base64.urlsafe_b64decode(payload_b64.encode("utf-8"))
        expected = hmac.new(settings.admin_auth_secret.encode("utf-8"), payload, hashlib.sha256).digest()
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


def get_optional_current_admin(
    request: Request,
    db: Session = Depends(get_db),
    session_cookie: str | None = Cookie(default=None, alias=settings.admin_session_cookie),
) -> CurrentAdmin | None:
    token = session_cookie or request.cookies.get(settings.admin_session_cookie)
    session_data = parse_admin_session_token(token)
    if session_data is None:
        return None
    admin = db.get(PlatformAdmin, int(session_data["admin_id"]))
    if admin is None or not admin.is_active:
        return None
    if admin.session_revoke_at is not None:
        token_iat = int(session_data.get("iat", 0))
        if int(admin.session_revoke_at.timestamp()) > token_iat:
            return None
    return CurrentAdmin(admin_id=admin.id, email=admin.email, display_name=admin.display_name, role=admin.role)


def get_current_admin(admin: CurrentAdmin | None = Depends(get_optional_current_admin)) -> CurrentAdmin:
    if admin is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin authentication required")
    return admin


def require_admin_write(admin: CurrentAdmin = Depends(get_current_admin)) -> CurrentAdmin:
    """Gate for every mutating admin-panel route. 'support'-role admins get the same read
    access as 'owner' but no create/update/delete anywhere in the panel - there was previously
    no role distinction at all, so any active admin account had full, uniform control over
    every tenant."""
    if admin.role != "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Read-only admin account")
    return admin
