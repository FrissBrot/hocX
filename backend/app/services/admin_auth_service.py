from __future__ import annotations

from datetime import UTC, datetime

from fastapi import HTTPException, Response, status
from sqlalchemy.orm import Session

from app.core.admin_security import CurrentAdmin, issue_admin_session_cookie
from app.core.config import settings
from app.core.rate_limit import check_account_lockout, record_failed_attempt
from app.core.security import DUMMY_PASSWORD_HASH, verify_password
from app.models import PlatformAdmin
from app.schemas.admin import AdminLoginRequest, AdminSelfRead, AdminSessionRead

# Account-scoped lockout, independent of source IP - see auth_service.py for the customer-login
# equivalent. Particularly relevant here since this is the highest-privilege account tier.
_ACCOUNT_LOGIN_ATTEMPT_LIMIT = 20
_ACCOUNT_LOGIN_WINDOW_SECONDS = 15 * 60


class AdminAuthService:
    def login(self, db: Session, response: Response, payload: AdminLoginRequest) -> AdminSessionRead:
        lockout_key = f"login-admin:{payload.email.strip().lower()}"
        check_account_lockout(lockout_key, limit=_ACCOUNT_LOGIN_ATTEMPT_LIMIT)

        admin = db.query(PlatformAdmin).filter(PlatformAdmin.email == payload.email).one_or_none()
        # See auth_service.py's identical fix - always run verify_password's full PBKDF2
        # work to avoid an email-enumeration timing side channel (audit finding, 2026-08-25).
        password_ok = verify_password(payload.password, admin.password_hash if admin is not None else DUMMY_PASSWORD_HASH)
        if admin is None or not admin.is_active or not password_ok:
            record_failed_attempt(lockout_key, period_seconds=_ACCOUNT_LOGIN_WINDOW_SECONDS)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

        issue_admin_session_cookie(response, admin.id)
        return self.session(
            CurrentAdmin(
                admin_id=admin.id, admin_public_id=admin.public_id, email=admin.email,
                display_name=admin.display_name, role=admin.role,
            )
        )

    def logout(self, db: Session, response: Response, admin: CurrentAdmin | None) -> dict[str, str]:
        response.delete_cookie(settings.admin_session_cookie, path="/")
        if admin is not None:
            # Admin session tokens are stateless (HMAC-signed, 12h TTL) - clearing the cookie
            # alone doesn't invalidate a copy of the token that leaked elsewhere. Bumping
            # session_revoke_at invalidates every outstanding token for this admin in one shot,
            # matching the pattern used for customer logout and admin deactivation.
            db_admin = db.get(PlatformAdmin, admin.admin_id)
            if db_admin is not None:
                db_admin.session_revoke_at = datetime.now(UTC)
                db.add(db_admin)
                db.commit()
        return {"message": "Logged out"}

    def session(self, admin: CurrentAdmin | None) -> AdminSessionRead:
        if admin is None:
            return AdminSessionRead(authenticated=False)
        return AdminSessionRead(
            authenticated=True,
            admin=AdminSelfRead(id=admin.admin_public_id, email=admin.email, display_name=admin.display_name, role=admin.role),
        )
