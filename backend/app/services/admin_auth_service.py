from __future__ import annotations

from fastapi import HTTPException, Response, status
from sqlalchemy.orm import Session

from app.core.admin_security import CurrentAdmin, create_admin_session_token
from app.core.config import settings
from app.core.security import verify_password
from app.models import PlatformAdmin
from app.schemas.admin import AdminLoginRequest, AdminSelfRead, AdminSessionRead


class AdminAuthService:
    def login(self, db: Session, response: Response, payload: AdminLoginRequest) -> AdminSessionRead:
        admin = db.query(PlatformAdmin).filter(PlatformAdmin.email == payload.email).one_or_none()
        if admin is None or not admin.is_active or not verify_password(payload.password, admin.password_hash):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

        token = create_admin_session_token(admin.id)
        response.set_cookie(
            key=settings.admin_session_cookie,
            value=token,
            httponly=True,
            secure=settings.auth_secure_cookies,
            samesite="lax",
            max_age=settings.admin_session_ttl_hours * 3600,
            path="/",
        )
        return self.session(CurrentAdmin(admin_id=admin.id, email=admin.email, display_name=admin.display_name))

    def logout(self, response: Response) -> dict[str, str]:
        response.delete_cookie(settings.admin_session_cookie, path="/")
        return {"message": "Logged out"}

    def session(self, admin: CurrentAdmin | None) -> AdminSessionRead:
        if admin is None:
            return AdminSessionRead(authenticated=False)
        return AdminSessionRead(
            authenticated=True,
            admin=AdminSelfRead(id=admin.admin_id, email=admin.email, display_name=admin.display_name),
        )
