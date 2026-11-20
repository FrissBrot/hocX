from __future__ import annotations

from datetime import UTC, datetime

from fastapi import HTTPException, Request, Response, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.admin_security import CurrentAdmin, issue_admin_session_cookie
from app.core.config import settings
from app.auth_security import context as request_context
from app.auth_security import devices, events
from app.auth_security.guard import LoginGuard
from app.core.security import DUMMY_PASSWORD_HASH, verify_password
from app.models import PlatformAdmin
from app.schemas.admin import AdminLoginRequest, AdminSelfRead, AdminSessionRead
from app.schemas.mfa import PasskeyAssertionStartRead, PasskeyRegistrationStartRead
from app.services.admin_mfa_service import AdminMfaService
from app.services.audit_service import AuditService

_audit = AuditService()


def _admin_device_known(db: Session, admin_id: int, device_hash: str | None) -> bool:
    """Gerät, von dem sich dieses Admin-Konto in der Gerätefrist schon erfolgreich angemeldet hat
    (``auth_event`` admin.login.success). Admins haben keine Geräteliste wie Konten; bekannt heisst
    hier nur: keine Warnung «neues Gerät» (Alarm admin_new_device) und bei Redis-Ausfall die lokale
    Notgrenze statt 503 (LoginGuard). Läuft auch für unbekannte E-Mails (Zeitverhalten)."""
    if not device_hash:
        return False
    return bool(db.scalar(
        text(
            "SELECT EXISTS (SELECT 1 FROM auth_event WHERE event_type = 'admin.login.success' AND outcome = 'success' "
            "AND platform_admin_id = :admin_id AND device_hash = :device_hash AND ts > now() - make_interval(days => :days))"
        ),
        {"admin_id": admin_id, "device_hash": device_hash, "days": settings.auth_device_ttl_days},
    ))


class AdminAuthService:
    def __init__(self) -> None:
        self.mfa_service = AdminMfaService()

    def login(
        self, db: Session, response: Response, payload: AdminLoginRequest, client_address: str | None = None,
        request: Request | None = None,
    ) -> AdminSessionRead:
        """Passwortphase mit dem Anmeldeschutz der Konten (app/auth_security/guard.py, Scope
        login-admin): gezählt wird VOR der Prüfung. IP-Sperren der Stufen 4/5 und kritische
        Abweisungen gelten hier nicht - der Admin-Zugang ist der Ziti-Notzugang (Audit 8.3); die
        Zähler je Konto und Konto+Quelle schon. Ein richtiges Passwort gibt nie eine Session."""
        guard = LoginGuard(scope="login-admin")
        ctx = request_context.current(client_address)
        admin = db.query(PlatformAdmin).filter(PlatformAdmin.email == payload.email).one_or_none()
        device_id = devices.device_id_from_request(request)
        device_hash = devices.device_hash(device_id) if device_id else None
        known = _admin_device_known(db, admin.id if admin is not None else -1, device_hash)
        check = guard.check(
            email=payload.email, ip=client_address, known_device=known, device_hash=device_hash, tenant_id=None,
            exempt_from_source_blocks=True,
        )
        # See auth_service.py's identical fix - always run verify_password's full PBKDF2
        # work to avoid an email-enumeration timing side channel (audit finding, 2026-08-25).
        password_ok = verify_password(payload.password, admin.password_hash if admin is not None else DUMMY_PASSWORD_HASH)
        if admin is None or not admin.is_active or not password_ok:
            guard.failed(check)
            reason = "unknown_account" if admin is None else ("inactive" if not admin.is_active else "password")
            events.record(
                ctx=ctx, event_type="admin.login.password", outcome="failure", actor_kind="admin",
                platform_admin_id=admin.id if admin is not None else None, subject_hash=check.subject, device_hash=device_hash,
                details={"reason": reason, "known_device": known},
            )
            # Sicherheitsereignis (PRIV-013): nur bekannte Admin-Konten werden benannt.
            _audit.log(
                db, action="admin.login_failed", outcome="failure",
                actor_email=admin.email if admin is not None else None,
                details={"reason": reason},
            )
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail={"code": "invalid_credentials", "message": "E-Mail oder Passwort ist ungültig."})
        guard.succeeded(check)
        events.record(
            ctx=ctx, event_type="admin.login.password", outcome="success", platform_admin_id=admin.id,
            subject_hash=check.subject, device_hash=device_hash, details={"known_device": known},
        )

        # Ein richtiges Passwort allein gibt nie eine Session: prepare_login liefert immer ein
        # Ticket - Passkey bestätigen oder (ohne Passkey) zuerst einen einrichten.
        pending_mfa = self.mfa_service.prepare_login(db, admin)
        return AdminSessionRead(authenticated=False, mfa=pending_mfa)

    def start_login_passkey(self, db: Session, *, ticket: str, request_host: str | None, request_origin: str) -> PasskeyAssertionStartRead:
        return self.mfa_service.start_login_passkey_assertion(db, ticket=ticket, request_host=request_host, request_origin=request_origin)

    def verify_login_passkey(
        self, db: Session, response: Response, *, flow_token: str, credential: dict, request: Request | None = None
    ) -> AdminSessionRead:
        context = self.mfa_service.verify_login_passkey(db, flow_token=flow_token, credential=credential)
        return self._finish_login(db, response, context.admin, method="password_passkey", request=request)

    def start_login_passkey_setup(self, db: Session, *, ticket: str, request_host: str | None, request_origin: str) -> PasskeyRegistrationStartRead:
        return self.mfa_service.start_login_passkey_setup(db, ticket=ticket, request_host=request_host, request_origin=request_origin)

    def complete_login_passkey_setup(
        self, db: Session, response: Response, *, flow_token: str, label: str | None, credential: dict, request: Request | None = None
    ) -> AdminSessionRead:
        context = self.mfa_service.complete_login_passkey_setup(db, flow_token=flow_token, label=label, credential=credential)
        _audit.log(db, action="admin.passkey_enrolled", actor_email=context.admin.email, details={"during": "login"})
        events.record(event_type="admin.mfa.enroll", outcome="success", platform_admin_id=context.admin.id, details={"factor": "passkey", "stage": "login"})
        return self._finish_login(db, response, context.admin, method="password_passkey_setup", request=request)

    def _finish_login(
        self, db: Session, response: Response, admin: PlatformAdmin, *, method: str, request: Request | None = None
    ) -> AdminSessionRead:
        issue_admin_session_cookie(response, admin.id)
        _audit.log(db, action="admin.login", actor_email=admin.email, details={"method": method})
        # Geräte-Cookie (host-only auf der Admin-Domain) für «neues Gerät» - Alarm admin_new_device
        device_id = devices.device_id_from_request(request)
        if device_id is None:
            device_id = devices.new_device_id()
            devices.set_cookie(response, device_id)
        device_hash = devices.device_hash(device_id)
        new_device = not _admin_device_known(db, admin.id, device_hash)
        events.record(
            event_type="admin.login.success", outcome="success", platform_admin_id=admin.id, device_hash=device_hash,
            details={"method": method, "new_device": new_device, "known_device": not new_device},
        )
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
            events.record(event_type="admin.logout", outcome="success", platform_admin_id=admin.admin_id)
        return {"message": "Logged out"}

    def session(self, admin: CurrentAdmin | None) -> AdminSessionRead:
        if admin is None:
            return AdminSessionRead(authenticated=False)
        return AdminSessionRead(
            authenticated=True,
            admin=AdminSelfRead(id=admin.admin_public_id, email=admin.email, display_name=admin.display_name, role=admin.role),
        )
