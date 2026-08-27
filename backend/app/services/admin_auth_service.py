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
from app.schemas.mfa import MfaTicketRequest, TotpEnrollmentComplete, TotpEnrollmentStartRead, TotpLoginVerifyRequest
from app.services.admin_mfa_service import AdminMfaService

# Account-scoped lockout, independent of source IP - see auth_service.py for the customer-login
# equivalent. Particularly relevant here since this is the highest-privilege account tier.
_ACCOUNT_LOGIN_ATTEMPT_LIMIT = 20
_ACCOUNT_LOGIN_WINDOW_SECONDS = 15 * 60


class AdminAuthService:
    def __init__(self) -> None:
        self.mfa_service = AdminMfaService()

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

        # Audit finding, 2026-08-27: a correct password alone used to grant a full,
        # unprotected session for the highest-privilege account tier in this system.
        # AdminMfaService.prepare_login never returns None - it always hands back a pending
        # ticket, either for TOTP verification (a factor already exists) or forced setup
        # (none yet), mirroring the tenant-admin MFA gate in auth_service.py/mfa_service.py.
        pending_mfa = self.mfa_service.prepare_login(db, admin)
        return AdminSessionRead(authenticated=False, mfa=pending_mfa)

    def verify_login_totp(self, db: Session, response: Response, payload: TotpLoginVerifyRequest) -> AdminSessionRead:
        context = self.mfa_service.verify_login_totp(db, ticket=payload.ticket, code=payload.code)
        return self._finish_login(response, context.admin)

    def start_login_totp_setup(self, db: Session, payload: MfaTicketRequest) -> TotpEnrollmentStartRead:
        return self.mfa_service.start_login_totp_enrollment(db, payload.ticket)

    def complete_login_totp_setup(
        self, db: Session, response: Response, payload: TotpEnrollmentComplete
    ) -> AdminSessionRead:
        context = self.mfa_service.complete_login_totp_enrollment(
            db, flow_token=payload.flow_token, code=payload.code, label=payload.label
        )
        return self._finish_login(response, context.admin)

    def _finish_login(self, response: Response, admin: PlatformAdmin) -> AdminSessionRead:
        issue_admin_session_cookie(response, admin.id, mfa_verified=True)
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
