from __future__ import annotations

from fastapi import HTTPException, Response, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import CurrentUser, build_current_user, create_session_token, verify_password
from app.models import AppUser
from app.schemas.user import LoginRequest, SessionRead, SessionUserRead, TenantMembershipRead, TenantRead
from app.services.tenant_service import build_tenant_profile_image_url


class AuthService:
    def login(self, db: Session, response: Response, payload: LoginRequest) -> SessionRead:
        user = db.query(AppUser).filter(AppUser.email == payload.email).one_or_none()
        if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

        current_user = build_current_user(db, user, payload.tenant_id)
        if not current_user.is_superadmin and current_user.current_tenant_id is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tenant membership assigned")

        token = create_session_token(user.id, current_user.current_tenant_id)
        response.set_cookie(
            key=settings.auth_session_cookie,
            value=token,
            httponly=True,
            secure=settings.auth_secure_cookies,
            samesite="lax",
            max_age=settings.auth_session_ttl_hours * 3600,
            path="/",
        )
        return self.session(current_user)

    def logout(self, response: Response) -> dict[str, str]:
        response.delete_cookie(settings.auth_session_cookie, path="/")
        return {"message": "Logged out"}

    def select_tenant(self, db: Session, response: Response, user: CurrentUser, tenant_id: int) -> SessionRead:
        if not user.is_superadmin and all(membership.tenant_id != tenant_id for membership in user.available_tenants):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant not assigned to current user")

        db_user = db.get(AppUser, user.user_id)
        refreshed = build_current_user(db, db_user, tenant_id) if db_user else None
        if refreshed is None or (not refreshed.is_superadmin and refreshed.current_tenant_id != tenant_id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant switch failed")

        token = create_session_token(user.user_id, tenant_id)
        response.set_cookie(
            key=settings.auth_session_cookie,
            value=token,
            httponly=True,
            secure=settings.auth_secure_cookies,
            samesite="lax",
            max_age=settings.auth_session_ttl_hours * 3600,
            path="/",
        )
        return self.session(refreshed)

    def session(self, user: CurrentUser | None) -> SessionRead:
        if user is None:
            return SessionRead(authenticated=False)

        current_tenant = None
        if user.current_tenant_id is not None and user.current_tenant_name is not None:
            current_tenant = TenantRead(
                id=user.current_tenant_id,
                name=user.current_tenant_name,
                profile_image_path=user.current_tenant_profile_image_path,
                profile_image_url=build_tenant_profile_image_url(user.current_tenant_id, user.current_tenant_profile_image_path),
            )

        return SessionRead(
            authenticated=True,
            user=SessionUserRead(
                id=user.user_id,
                first_name=user.first_name,
                last_name=user.last_name,
                display_name=user.display_name,
                email=user.email,
                preferred_language=user.preferred_language,
                is_superadmin=user.is_superadmin,
            ),
            current_tenant=current_tenant,
            current_role=user.current_role,
            available_tenants=[
                TenantMembershipRead(
                    tenant_id=membership.tenant_id,
                    tenant_name=membership.tenant_name,
                    tenant_profile_image_path=membership.tenant_profile_image_path,
                    role_code=membership.role_code,
                    is_active=membership.is_active,
                )
                for membership in user.available_tenants
            ],
        )
