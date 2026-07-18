from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import Cookie, Depends, HTTPException, Request, status
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
    return CurrentAdmin(admin_id=admin.id, email=admin.email, display_name=admin.display_name)


def get_current_admin(admin: CurrentAdmin | None = Depends(get_optional_current_admin)) -> CurrentAdmin:
    if admin is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin authentication required")
    return admin
