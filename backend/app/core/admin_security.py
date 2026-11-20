from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
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
    admin_public_id: uuid.UUID
    email: str
    display_name: str
    role: str = "owner"


def _sign_payload(payload: bytes) -> str:
    signature = hmac.new(settings.admin_auth_secret.encode("utf-8"), payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(payload).decode("utf-8") + "." + base64.urlsafe_b64encode(signature).decode("utf-8")


# Einzige Anmeldeart seit 0205: Passwort + Passkey. Tokens ohne diesen Claim (TOTP- und SSO-Sessions
# bis 1.4.x) gelten nicht mehr.
SESSION_AMR = "passkey"


def create_admin_session_token(admin_id: int) -> str:
    now = datetime.now(UTC)
    payload = json.dumps(
        {
            "admin_id": admin_id,
            "mfa": True,
            "amr": SESSION_AMR,
            "iat": int(now.timestamp()),
            # Millisekunden (Review L5): ein Widerruf in derselben Sekunde wie die Ausstellung
            # entscheidet sonst je nach Rundung falsch.
            "iat_ms": int(now.timestamp() * 1000),
            "exp": int((now + timedelta(hours=settings.admin_session_ttl_hours)).timestamp()),
        },
        separators=(",", ":"),
    ).encode("utf-8")
    return _sign_payload(payload)


def issue_admin_session_cookie(response: Response, admin_id: int) -> None:
    """Session als host-only Cookie - nur nach Passwort UND erfolgreichem Passkey
    (AdminAuthService._finish_login). Einen anderen Weg zu einer Admin-Session gibt es nicht."""
    token = create_admin_session_token(admin_id)
    response.set_cookie(
        key=settings.admin_session_cookie,
        value=token,
        httponly=True,
        secure=settings.auth_secure_cookies,
        # Strict (SEC-AUTH-001): das Admin-Panel braucht keine Cross-Site-Navigation mit Session.
        # Kommt man über einen Link von einer anderen Seite, fehlt das Cookie beim ersten Aufruf
        # von /admin - die Login-Seite erkennt die Session dann per Same-Site-Fetch und leitet weiter. Host-only (kein domain=): gilt nur für die Admin-Domain.
        samesite="strict",
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
        # Ältere Tokens ohne iat_ms: Anfang ihrer Ausstellungssekunde - ein Widerruf in derselben
        # Sekunde trifft sie dann sicher (>=), statt je nach Rundung nicht.
        token_iat_ms = int(session_data.get("iat_ms") or int(session_data.get("iat", 0)) * 1000)
        if int(admin.session_revoke_at.timestamp() * 1000) >= token_iat_ms:
            return None
    # Audit finding, 2026-08-27: platform admins are the highest-privilege tier (full
    # cross-tenant access, backup export, admin management) but previously had no MFA
    # option at all - password-only login granted a full, unprotected session. Every
    # session token minted since this fix carries an explicit "mfa" claim, set True only
    # after a completed second factor (since 0205: passkey only, claim amr=passkey - TOTP and
    # SSO were removed, their tokens no longer count). A token with no such claim
    # (including every token minted before this fix) is rejected outright, forcing
    # re-authentication through the new MFA-aware login flow rather than silently granting
    # the old, weaker session shape.
    if not bool(session_data.get("mfa")) or session_data.get("amr") != SESSION_AMR:
        return None
    return CurrentAdmin(
        admin_id=admin.id, admin_public_id=admin.public_id, email=admin.email, display_name=admin.display_name, role=admin.role
    )


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


def require_admin_owner(admin: CurrentAdmin = Depends(get_current_admin)) -> CurrentAdmin:
    """Gate sensitive read operations that expose cross-tenant PII or security data."""
    if admin.role != "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Owner admin account required")
    return admin
