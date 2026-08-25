from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, Response, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import check_account_lockout, record_failed_attempt
from app.core.security import CurrentUser, DUMMY_PASSWORD_HASH, build_current_user, issue_session_cookie, verify_password
from app.models import AppUser
from app.schemas.mfa import (
    LoginResponse,
    MfaTicketRequest,
    PasskeyAssertionStartRead,
    PasskeyAssertionVerifyRequest,
    PasskeyRegistrationComplete,
    PasskeyRegistrationStartRead,
    TotpEnrollmentComplete,
    TotpEnrollmentStartRead,
    TotpLoginVerifyRequest,
)
from app.schemas.user import LoginRequest, SessionRead, SessionUserRead, TenantMembershipRead, TenantRead
from app.services import domain_bridge_service
from app.services.audit_service import AuditService
from app.services.mfa_service import MfaService
from app.services.tenant_service import build_tenant_profile_image_url

_audit = AuditService()

# Account-scoped lockout, independent of source IP - complements Traefik's per-IP rate limit
# (10/min), which a distributed or shared-IP bruteforce attempt can bypass entirely.
_ACCOUNT_LOGIN_ATTEMPT_LIMIT = 20
_ACCOUNT_LOGIN_WINDOW_SECONDS = 15 * 60


class AuthService:
    def __init__(self) -> None:
        self.mfa_service = MfaService()

    def login(self, db: Session, response: Response, payload: LoginRequest, request_host: str | None = None) -> LoginResponse:
        lockout_key = f"login-account:{payload.email.strip().lower()}"
        check_account_lockout(lockout_key, limit=_ACCOUNT_LOGIN_ATTEMPT_LIMIT)

        user = db.query(AppUser).filter(AppUser.email == payload.email).one_or_none()
        # Always run verify_password's full PBKDF2 work, even for a nonexistent account
        # (against DUMMY_PASSWORD_HASH) - short-circuiting past it was a timing side
        # channel that let an attacker enumerate valid emails (audit finding, 2026-08-25).
        password_ok = verify_password(payload.password, user.password_hash if user is not None else DUMMY_PASSWORD_HASH)
        if user is None or not user.is_active or not password_ok:
            record_failed_attempt(lockout_key, period_seconds=_ACCOUNT_LOGIN_WINDOW_SECONDS)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
        if (user.external_identity_json or {}).get("login_enabled") is False:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Login is disabled for this account")

        current_user = build_current_user(db, user, payload.tenant_id)
        if current_user.current_tenant_id is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tenant membership assigned")

        pending_mfa = self.mfa_service.prepare_login(
            db,
            user=user,
            current_user=current_user,
            request_host=request_host,
        )
        if pending_mfa is not None:
            return LoginResponse(authenticated=False, mfa=pending_mfa)

        return self._finish_login(
            db,
            response,
            user=user,
            tenant_id=current_user.current_tenant_id,
            request_host=request_host,
            mfa_verified=False,
        )

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
        user_id, tenant_id, mfa_verified = pair

        user = db.get(AppUser, user_id)
        if user is None or not user.is_active:
            return False
        current_user = build_current_user(db, user, tenant_id, mfa_verified=mfa_verified)
        if current_user.current_tenant_id != tenant_id:
            return False

        issue_session_cookie(response, user_id, tenant_id, mfa_verified=mfa_verified)
        return True

    def select_tenant(
        self, db: Session, response: Response, user: CurrentUser, tenant_id: int, request_host: str | None = None
    ) -> SessionRead:
        if all(membership.tenant_id != tenant_id for membership in user.available_tenants):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant not assigned to current user")

        db_user = db.get(AppUser, user.user_id)
        refreshed = build_current_user(db, db_user, tenant_id, mfa_verified=user.mfa_verified) if db_user else None
        if refreshed is None or refreshed.current_tenant_id != tenant_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant switch failed")

        issue_session_cookie(response, user.user_id, tenant_id, mfa_verified=user.mfa_verified)
        bridge_redirect_url = domain_bridge_service.resolve_bridge_redirect(
            db,
            request_host,
            user.user_id,
            tenant_id,
            mfa_verified=user.mfa_verified,
        )
        return self.session(refreshed, bridge_redirect_url)

    def verify_login_totp(
        self, db: Session, response: Response, payload: TotpLoginVerifyRequest
    ) -> LoginResponse:
        context = self.mfa_service.verify_login_totp(db, ticket=payload.ticket, code=payload.code)
        return self._finish_login(
            db,
            response,
            user=context.user,
            tenant_id=context.current_user.current_tenant_id,
            request_host=context.request_host,
            mfa_verified=True,
        )

    def start_login_totp_setup(self, db: Session, payload: MfaTicketRequest) -> TotpEnrollmentStartRead:
        return self.mfa_service.start_login_totp_enrollment(db, payload.ticket)

    def complete_login_totp_setup(
        self,
        db: Session,
        response: Response,
        payload: TotpEnrollmentComplete,
    ) -> LoginResponse:
        context = self.mfa_service.complete_login_totp_enrollment(
            db,
            flow_token=payload.flow_token,
            code=payload.code,
            label=payload.label,
        )
        return self._finish_login(
            db,
            response,
            user=context.user,
            tenant_id=context.current_user.current_tenant_id,
            request_host=context.request_host,
            mfa_verified=True,
        )

    def start_login_passkey_setup(
        self,
        db: Session,
        payload: MfaTicketRequest,
        *,
        request_host: str | None,
        request_origin: str,
    ) -> PasskeyRegistrationStartRead:
        return self.mfa_service.start_login_passkey_registration(
            db,
            payload.ticket,
            request_host=request_host,
            request_origin=request_origin,
        )

    def complete_login_passkey_setup(
        self,
        db: Session,
        response: Response,
        payload: PasskeyRegistrationComplete,
    ) -> LoginResponse:
        context = self.mfa_service.complete_login_passkey_registration(
            db,
            flow_token=payload.flow_token,
            label=payload.label,
            credential=payload.credential,
        )
        return self._finish_login(
            db,
            response,
            user=context.user,
            tenant_id=context.current_user.current_tenant_id,
            request_host=context.request_host,
            mfa_verified=True,
        )

    def start_login_passkey_assertion(
        self,
        db: Session,
        payload: MfaTicketRequest,
        *,
        request_host: str | None,
        request_origin: str,
    ) -> PasskeyAssertionStartRead:
        return self.mfa_service.start_login_passkey_assertion(
            db,
            ticket=payload.ticket,
            request_host=request_host,
            request_origin=request_origin,
        )

    def verify_login_passkey(
        self,
        db: Session,
        response: Response,
        payload: PasskeyAssertionVerifyRequest,
    ) -> LoginResponse:
        context = self.mfa_service.verify_login_passkey(
            db,
            flow_token=payload.flow_token,
            credential=payload.credential,
        )
        return self._finish_login(
            db,
            response,
            user=context.user,
            tenant_id=context.current_user.current_tenant_id,
            request_host=context.request_host,
            mfa_verified=True,
        )

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
                protocol_accordion_enabled=user.protocol_accordion_enabled,
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

    def _finish_login(
        self,
        db: Session,
        response: Response,
        *,
        user: AppUser,
        tenant_id: int | None,
        request_host: str | None,
        mfa_verified: bool,
    ) -> LoginResponse:
        current_user = build_current_user(db, user, tenant_id, mfa_verified=mfa_verified)
        if current_user.current_tenant_id is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tenant membership assigned")
        issue_session_cookie(response, user.id, current_user.current_tenant_id, mfa_verified=mfa_verified)
        _audit.log(db, action="user.login", actor=current_user)
        bridge_redirect_url = domain_bridge_service.resolve_bridge_redirect(
            db,
            request_host,
            user.id,
            current_user.current_tenant_id,
            mfa_verified=mfa_verified,
        )
        return LoginResponse(**self.session(current_user, bridge_redirect_url).model_dump(), mfa=None)
