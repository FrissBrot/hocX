from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, Response, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import CurrentUser, build_current_user, issue_session_cookie, verify_password
from app.models import AppUser
from app.schemas.user import LoginRequest, SessionRead, SessionUserRead, TenantMembershipRead, TenantRead
from app.services import domain_bridge_service
from app.services.audit_service import AuditService
from app.services.tenant_service import build_tenant_profile_image_url

_audit = AuditService()


class AuthService:
    def login(self, db: Session, response: Response, payload: LoginRequest, request_host: str | None = None) -> SessionRead:
        user = db.query(AppUser).filter(AppUser.email == payload.email).one_or_none()
        if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
        if (user.external_identity_json or {}).get("login_enabled") is False:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Login is disabled for this account")

        current_user = build_current_user(db, user, payload.tenant_id)
        if current_user.current_tenant_id is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tenant membership assigned")

        issue_session_cookie(response, user.id, current_user.current_tenant_id)
        _audit.log(db, action="user.login", actor=current_user)
        bridge_redirect_url = domain_bridge_service.resolve_bridge_redirect(
            db, request_host, user.id, current_user.current_tenant_id
        )
        return self.session(current_user, bridge_redirect_url)

    def logout(self, db: Session, response: Response, user: CurrentUser | None) -> dict[str, str]:
        response.delete_cookie(settings.auth_session_cookie, path="/")
        if user is not None:
            # Session tokens are stateless (HMAC-signed, no server-side session table), and a
            # tenant with a custom domain means a user can end up with a valid cookie on more
            # than one origin at once (main domain + one or more custom domains) - clearing only
            # the cookie for whichever origin this logout request came from would leave the
            # others silently still logged in. session_revoke_at invalidates every outstanding
            # token for this user in one shot, regardless of which domain's cookie holds it.
            db_user = db.get(AppUser, user.user_id)
            if db_user is not None:
                db_user.session_revoke_at = datetime.now(timezone.utc)
                db.add(db_user)
                db.commit()
        return {"message": "Logged out"}

    def redeem_bridge_token(self, db: Session, response: Response, token: str) -> bool:
        """Consumes a single-use domain-bridge token and, if valid, issues a session cookie
        scoped to whichever domain this request came in on. Returns False on an invalid/expired
        token - the caller sends the browser back to the main-domain login in that case."""
        pair = domain_bridge_service.consume_bridge_token(token)
        if pair is None:
            return False
        user_id, tenant_id = pair

        user = db.get(AppUser, user_id)
        if user is None or not user.is_active:
            return False
        current_user = build_current_user(db, user, tenant_id)
        if current_user.current_tenant_id != tenant_id:
            return False

        issue_session_cookie(response, user_id, tenant_id)
        return True

    def select_tenant(
        self, db: Session, response: Response, user: CurrentUser, tenant_id: int, request_host: str | None = None
    ) -> SessionRead:
        if all(membership.tenant_id != tenant_id for membership in user.available_tenants):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant not assigned to current user")

        db_user = db.get(AppUser, user.user_id)
        refreshed = build_current_user(db, db_user, tenant_id) if db_user else None
        if refreshed is None or refreshed.current_tenant_id != tenant_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant switch failed")

        issue_session_cookie(response, user.user_id, tenant_id)
        bridge_redirect_url = domain_bridge_service.resolve_bridge_redirect(db, request_host, user.user_id, tenant_id)
        return self.session(refreshed, bridge_redirect_url)

    def session(self, user: CurrentUser | None, bridge_redirect_url: str | None = None) -> SessionRead:
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
            bridge_redirect_url=bridge_redirect_url,
            user=SessionUserRead(
                id=user.user_id,
                first_name=user.first_name,
                last_name=user.last_name,
                display_name=user.display_name,
                email=user.email,
                preferred_language=user.preferred_language,
                default_tenant_id=user.default_tenant_id,
            ),
            current_tenant=current_tenant,
            current_role=user.current_role,
            available_tenants=[
                TenantMembershipRead(
                    tenant_id=membership.tenant_id,
                    tenant_name=membership.tenant_name,
                    tenant_profile_image_path=membership.tenant_profile_image_path,
                    tenant_profile_image_url=build_tenant_profile_image_url(membership.tenant_id, membership.tenant_profile_image_path),
                    role_code=membership.role_code,
                    is_active=membership.is_active,
                )
                for membership in user.available_tenants
            ],
        )
