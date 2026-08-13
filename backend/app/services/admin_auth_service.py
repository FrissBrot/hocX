from __future__ import annotations

from datetime import UTC, datetime

from fastapi import HTTPException, Response, status
from sqlalchemy.orm import Session

from app.core.admin_security import CurrentAdmin, issue_admin_session_cookie
from app.core.config import settings
from app.core.security import verify_password
from app.models import PlatformAdmin
from app.schemas.admin import AdminLoginRequest, AdminSelfRead, AdminSessionRead


class AdminAuthService:
    def login(self, db: Session, response: Response, payload: AdminLoginRequest) -> AdminSessionRead:
        admin = db.query(PlatformAdmin).filter(PlatformAdmin.email == payload.email).one_or_none()
        if admin is None or not admin.is_active or not verify_password(payload.password, admin.password_hash):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

        issue_admin_session_cookie(response, admin.id)
        return self.session(CurrentAdmin(admin_id=admin.id, email=admin.email, display_name=admin.display_name))

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
            admin=AdminSelfRead(id=admin.admin_id, email=admin.email, display_name=admin.display_name),
        )
