from __future__ import annotations

from datetime import UTC, datetime

from fastapi import HTTPException, Response, status
from sqlalchemy.orm import Session

from app.core.admin_security import CurrentAdmin, issue_admin_session_cookie
from app.core.config import settings
from app.core.rate_limit import check_login_lockout, record_failed_login
from app.core.security import DUMMY_PASSWORD_HASH, verify_password
from app.models import PlatformAdmin
from app.schemas.admin import AdminLoginRequest, AdminSelfRead, AdminSessionRead
from app.schemas.mfa import PasskeyAssertionStartRead, PasskeyRegistrationStartRead
from app.services.admin_mfa_service import AdminMfaService
from app.services.audit_service import AuditService

_audit = AuditService()


class AdminAuthService:
    def __init__(self) -> None:
        self.mfa_service = AdminMfaService()

    def login(
        self, db: Session, response: Response, payload: AdminLoginRequest, client_address: str | None = None,
    ) -> AdminSessionRead:
        # Sperre pro Konto und Quell-IP plus höhere Grenze pro Konto (MAIN-SEC-007), wie im
        # Kunden-Login (auth_service.py).
        check_login_lockout("login-admin", payload.email, client_address)

        admin = db.query(PlatformAdmin).filter(PlatformAdmin.email == payload.email).one_or_none()
        # See auth_service.py's identical fix - always run verify_password's full PBKDF2
        # work to avoid an email-enumeration timing side channel (audit finding, 2026-08-25).
        password_ok = verify_password(payload.password, admin.password_hash if admin is not None else DUMMY_PASSWORD_HASH)
        if admin is None or not admin.is_active or not password_ok:
            record_failed_login("login-admin", payload.email, client_address)
            # Sicherheitsereignis (PRIV-013): nur bekannte Admin-Konten werden benannt.
            _audit.log(
                db, action="admin.login_failed", outcome="failure",
                actor_email=admin.email if admin is not None else None,
                details={"reason": "unknown_account" if admin is None else ("inactive" if not admin.is_active else "password")},
            )
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail={"code": "invalid_credentials", "message": "E-Mail oder Passwort ist ungültig."})

        # Ein richtiges Passwort allein gibt nie eine Session: prepare_login liefert immer ein
        # Ticket - Passkey bestätigen oder (ohne Passkey) zuerst einen einrichten.
        pending_mfa = self.mfa_service.prepare_login(db, admin)
        return AdminSessionRead(authenticated=False, mfa=pending_mfa)

    def start_login_passkey(self, db: Session, *, ticket: str, request_host: str | None, request_origin: str) -> PasskeyAssertionStartRead:
        return self.mfa_service.start_login_passkey_assertion(db, ticket=ticket, request_host=request_host, request_origin=request_origin)

    def verify_login_passkey(self, db: Session, response: Response, *, flow_token: str, credential: dict) -> AdminSessionRead:
        context = self.mfa_service.verify_login_passkey(db, flow_token=flow_token, credential=credential)
        return self._finish_login(db, response, context.admin, method="password_passkey")

    def start_login_passkey_setup(self, db: Session, *, ticket: str, request_host: str | None, request_origin: str) -> PasskeyRegistrationStartRead:
        return self.mfa_service.start_login_passkey_setup(db, ticket=ticket, request_host=request_host, request_origin=request_origin)

    def complete_login_passkey_setup(
        self, db: Session, response: Response, *, flow_token: str, label: str | None, credential: dict
    ) -> AdminSessionRead:
        context = self.mfa_service.complete_login_passkey_setup(db, flow_token=flow_token, label=label, credential=credential)
        _audit.log(db, action="admin.passkey_enrolled", actor_email=context.admin.email, details={"during": "login"})
        return self._finish_login(db, response, context.admin, method="password_passkey_setup")

    def _finish_login(self, db: Session, response: Response, admin: PlatformAdmin, *, method: str) -> AdminSessionRead:
        issue_admin_session_cookie(response, admin.id)
        _audit.log(db, action="admin.login", actor_email=admin.email, details={"method": method})
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
