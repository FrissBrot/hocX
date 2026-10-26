from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, Response, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import check_login_lockout, record_failed_login
from app.schemas.role import RoleRef
from app.core.security import CurrentUser, DUMMY_PASSWORD_HASH, build_current_user, issue_locale_cookie, issue_session_cookie, verify_password
from app.models import AppUser, Tenant
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
from app.schemas.user import BridgePreviewRead, LoginRequest, SessionRead, SessionUserRead, TenantRead
from app.services import domain_bridge_service
from app.services.audit_service import AuditService
from app.services.mfa_service import MfaService
from app.services.tenant_service import build_tenant_profile_image_url

_audit = AuditService()



class AuthService:
    def __init__(self) -> None:
        self.mfa_service = MfaService()

    def login(
        self,
        db: Session,
        response: Response,
        payload: LoginRequest,
        request_host: str | None = None,
        client_address: str | None = None,
    ) -> LoginResponse:
        # Sperre pro Konto und Quell-IP plus höhere Grenze pro Konto (MAIN-SEC-007).
        check_login_lockout("login-account", payload.email, client_address)

        user = db.query(AppUser).filter(AppUser.email == payload.email.strip().lower(), AppUser.login_enabled.is_(True)).one_or_none()
        # Always run verify_password's full PBKDF2 work, even for a nonexistent account
        # (against DUMMY_PASSWORD_HASH) - short-circuiting past it was a timing side
        # channel that let an attacker enumerate valid emails (audit finding, 2026-08-25).
        password_ok = verify_password(payload.password, user.password_hash if user is not None and user.password_hash else DUMMY_PASSWORD_HASH)
        if user is None or not user.is_active or not password_ok:
            record_failed_login("login-account", payload.email, client_address)
            # Sicherheitsereignis (PRIV-013): die eingegebene E-Mail wird nicht gespeichert, nur das
            # Konto, falls es existiert, und die gehashte Quelle (audit_context).
            _audit.log(
                db, action="user.login_failed", outcome="failure",
                tenant_id=user.tenant_id if user is not None else None,
                actor_user_id=user.id if user is not None else None,
                details={"reason": "unknown_account" if user is None else ("inactive" if not user.is_active else "password")},
            )
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="E-Mail oder Passwort ist ungültig.")
        if not user.login_enabled:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Login ist für dieses Konto deaktiviert.")

        current_user = build_current_user(db, user)

        pending_mfa = self.mfa_service.prepare_login(
            db,
            user=user,
            current_user=current_user,
            request_host=request_host,
        )
        if pending_mfa is not None:
            return LoginResponse(authenticated=False, mfa=pending_mfa)

        return self._finish_login(db, response, user=user, request_host=request_host, mfa_verified=False)

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

    @staticmethod
    def _may_use_bridge(user: AppUser | None) -> bool:
        """Dieselben Kontoprüfungen wie bei jedem Request (get_optional_current_user), schon beim
        Einlösen: aktiv, Login erlaubt, keine Session-Beendigung seit Ausstellung des Tokens."""
        return (
            user is not None
            and user.is_active
            and user.login_enabled
            and not domain_bridge_service.token_predates_session_revoke(user.session_revoke_at)
        )

    def preview_bridge_token(self, db: Session, token: str, request_host: str | None) -> BridgePreviewRead | None:
        """Für die Bestätigungsseite auf der Ziel-Domain (MAIN-SEC-006): zeigt, als wer man
        angemeldet würde, ohne das Token zu verbrauchen. None bei ungültigem, abgelaufenem
        oder auf einer fremden Domain vorgelegtem Token."""
        bridge = domain_bridge_service.peek_bridge_token(token, request_host)
        if bridge is None:
            return None
        user = db.get(AppUser, bridge.user_id)
        if not self._may_use_bridge(user):
            return None
        tenant = db.get(Tenant, user.tenant_id)
        return BridgePreviewRead(
            display_name=user.display_name,
            email=user.email,
            tenant_name=tenant.name if tenant is not None else "",
        )

    def redeem_bridge_token(self, db: Session, response: Response, token: str, request_host: str | None) -> bool:
        """Consumes a single-use domain-bridge token and, if valid for this host, issues a
        session cookie scoped to it. Only called after the user confirmed the handoff on the
        confirmation page (MAIN-SEC-006) - a link alone no longer logs anybody in."""
        bridge = domain_bridge_service.consume_bridge_token(token, request_host)
        if bridge is None:
            return False

        user = db.get(AppUser, bridge.user_id)
        if not self._may_use_bridge(user):
            return False

        issue_session_cookie(response, bridge.user_id, mfa_verified=bridge.mfa_verified)
        issue_locale_cookie(response, user.preferred_language)
        return True

    def verify_login_totp(
        self, db: Session, response: Response, payload: TotpLoginVerifyRequest
    ) -> LoginResponse:
        context = self.mfa_service.verify_login_totp(db, ticket=payload.ticket, code=payload.code)
        return self._finish_login(
            db,
            response,
            user=context.user,
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
            request_host=context.request_host,
            mfa_verified=True,
        )

    def session(self, user: CurrentUser | None, response: Response, bridge_redirect_url: str | None = None) -> SessionRead:
        if user is None:
            return SessionRead(authenticated=False)

        # Haelt den Locale-Cookie bei jedem Session-Abruf frisch, falls preferred_language auf
        # einem anderen Geraet geaendert wurde (siehe issue_locale_cookie-Docstring) - deckt
        # Prioritaetsstufe 1 ("explizit gespeicherte Benutzerpraeferenz") ab, ohne dass next-intl
        # selbst einen Backend-Request braucht.
        issue_locale_cookie(response, user.preferred_language)

        current_tenant = TenantRead(
            id=user.current_tenant_public_id,
            name=user.current_tenant_name,
            profile_image_path=user.current_tenant_profile_image_path,
            profile_image_url=build_tenant_profile_image_url(user.current_tenant_public_id, user.current_tenant_profile_image_path),
            enabled_features=sorted(user.current_tenant_features),
        )

        return SessionRead(
            authenticated=True,
            bridge_redirect_url=bridge_redirect_url,
            user=SessionUserRead(
                id=user.user_public_id,
                first_name=user.first_name,
                last_name=user.last_name,
                display_name=user.display_name,
                email=user.email,
                preferred_language=user.preferred_language,
                protocol_accordion_enabled=user.protocol_accordion_enabled,
            ),
            current_tenant=current_tenant,
            permissions=sorted(user.permissions),
            roles=[RoleRef(id=role.public_id, name=role.name, system_key=role.system_key) for role in user.roles],
        )

    def _finish_login(
        self,
        db: Session,
        response: Response,
        *,
        user: AppUser,
        request_host: str | None,
        mfa_verified: bool,
    ) -> LoginResponse:
        current_user = build_current_user(db, user, mfa_verified=mfa_verified)
        issue_session_cookie(response, user.id, mfa_verified=mfa_verified)
        issue_locale_cookie(response, user.preferred_language)
        _audit.log(db, action="user.login", actor=current_user)
        bridge_redirect_url = domain_bridge_service.resolve_bridge_redirect(
            db,
            request_host,
            user.id,
            current_user.current_tenant_id,
            mfa_verified=mfa_verified,
        )
        return LoginResponse(**self.session(current_user, response, bridge_redirect_url).model_dump(), mfa=None)
