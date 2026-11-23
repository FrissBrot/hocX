from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import BackgroundTasks, HTTPException, Request, Response, status
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.auth_security import devices, email_challenge, events, notify, risk
from app.auth_security import context as request_context
from app.auth_security import sessions as session_register
from app.auth_security.guard import (
    LoginGuard,
    count_device_failure,
    count_invalid_token,
    device_failures,
    mark_locked,
    pop_locked,
    tenant_accounts_observe,
)
from app.core.auth_pseudonym import normalize_email
from app.core.config import settings
from app.core.permissions import requires_mfa
from app.schemas.role import RoleRef
from app.core.security import (
    CurrentUser,
    DUMMY_PASSWORD_HASH,
    build_current_user,
    clear_session_cookies,
    issue_locale_cookie,
    issue_session_cookie,
    load_role_permissions,
    verify_password,
)
from app.models import AppUser, AuthKnownDevice, Tenant
from app.notifications import delivery_status
from app.schemas.mfa import (
    EmailChallengeVerifyRequest,
    LoginResponse,
    MfaPendingLoginRead,
    MfaSkipRequest,
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


def _login_denied() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={"code": "login_denied", "message": "Anmeldung von dieser Verbindung vorübergehend nicht möglich"},
        headers={"Retry-After": "900"},
    )


def _notify_failed_attempts(user_id: int, count: int) -> None:
    """Hinweis-Mail «viele Fehlversuche» in eigener Session (nach der Antwort)."""
    from app.core.db import SessionLocal
    from app.core.error_log import record_system_error

    with SessionLocal() as session:
        try:
            user = session.get(AppUser, user_id)
            if user is not None:
                notify.failed_attempts(session, user, count=count)
                session.commit()
        except Exception as exc:  # noqa: BLE001 - ausserhalb des Requests: selbst ins Fehlerprotokoll
            session.rollback()
            record_system_error(session, exc=exc)



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
        request: Request | None = None,
        background: BackgroundTasks | None = None,
    ) -> LoginResponse:
        """Passwortphase mit Anmeldeschutz (app/auth_security/guard.py): Sperren und Zähler
        werden VOR der Passwortprüfung gezählt (SEC-AUTH-003), bekannte Geräte sind von der
        Kontosperre ausgenommen (SEC-AUTH-006), die Risk Engine entscheidet über eine zusätzliche
        Prüfung (zweiter Faktor oder E-Mail-Code).

        Ohne E-Mail-Versand wird nur bei Quellsignalen (L1/L2) oder über L5 abgewiesen, und zwar
        einheitlich für falsches Passwort und für korrektes Passwort ohne Faktor (kein Orakel);
        Konten mit Faktor werden nie abgewiesen, der Faktor ist die Prüfung (Security-Review M2/M3).
        Existierende und unbekannte Konten durchlaufen dieselben Redis-/DB-Schritte (N3)."""
        email = normalize_email(payload.email)
        guard = LoginGuard()
        ctx = request_context.current(client_address)
        user = db.query(AppUser).filter(AppUser.email == email, AppUser.login_enabled.is_(True)).one_or_none()
        device_id = devices.device_id_from_request(request)
        # Gleiche Abfrage auch für unbekannte Konten (Zeitverhalten, Security-Review N3)
        known = devices.known_device(db, user.id if user is not None else -1, device_id)
        device_hash = devices.device_hash(device_id) if device_id else None
        if known is not None and device_failures(device_hash) >= settings.auth_account_ip_failures:
            # Fehlversuche je Gerät (Security-Review M4): ein bekanntes Gerät, von dem aus geraten
            # wird, verliert seine Ausnahme von den Sperren.
            known = None
        check = guard.check(email=email, ip=client_address, known_device=known is not None, device_hash=device_hash, tenant_id=user.tenant_id if user is not None else None)
        smtp = email_challenge.available(db)
        deny_without_smtp = (
            known is None and risk.enforcing() and not smtp and (check.source_soft or check.account_locked or (check.pre is not None and check.pre.level == risk.HIGH))
        )

        # Always run verify_password's full PBKDF2 work, even for a nonexistent account
        # (against DUMMY_PASSWORD_HASH) - short-circuiting past it was a timing side
        # channel that let an attacker enumerate valid emails (audit finding, 2026-08-25).
        password_ok = verify_password(payload.password, user.password_hash if user is not None and user.password_hash else DUMMY_PASSWORD_HASH)
        # Ausgetreten: wie ein falsches Passwort (SEC-AUTH-016 - früher 403 nur bei korrektem
        # Passwort, ein Passwort-Orakel für ehemalige Mitglieder).
        if user is None or not user.is_active or user.has_left or not password_ok:
            guard.failed(check)
            count_device_failure(device_hash)
            reason = "unknown_account" if user is None else ("inactive" if not user.is_active else ("left" if user.has_left else "password"))
            events.record(
                ctx=ctx,
                event_type="login.password", outcome="blocked" if deny_without_smtp else "failure", user_id=user.id if user else None,
                tenant_id=user.tenant_id if user else None, subject_hash=check.subject, device_hash=device_hash,
                risk_score=check.pre.score if check.pre else None, risk_reasons=check.pre.reasons if check.pre else (),
                risk_weights=check.pre.weights if check.pre else None,
                enforcement="deny" if deny_without_smtp else "none", details={"reason": reason, "known_device": known is not None},
            )
            # Sicherheitsereignis (PRIV-013): die eingegebene E-Mail wird nicht gespeichert, nur das
            # Konto, falls es existiert, und die gehashte Quelle (audit_context).
            _audit.log(
                db, action="user.login_failed", outcome="failure",
                tenant_id=user.tenant_id if user is not None else None,
                actor_user_id=user.id if user is not None else None,
                details={"reason": reason},
            )
            tenant_accounts_observe(user.tenant_id if user is not None else 0, check.subject)
            failures = check.account_failures
            if failures >= settings.auth_account_failures_known_only:
                mark_locked(user.id if user is not None else -1)
            if user is not None and failures >= settings.auth_account_failures_challenge:
                # Nach der Antwort verschickt (Zeitverhalten, Security-Review N3)
                if background is not None:
                    background.add_task(_notify_failed_attempts, user.id, failures)
                else:
                    notify.failed_attempts(db, user, count=failures)
                    db.commit()
            if deny_without_smtp:
                raise _login_denied()
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail={"code": "invalid_credentials", "message": "E-Mail oder Passwort ist ungültig."})
        guard.succeeded(check)

        permissions, _role_ids = load_role_permissions(db, user.id)
        if check.degraded:
            assessment = risk.Assessment(score=0, reasons=["degraded"], level=risk.NORMAL)
        else:
            assessment = guard.full_assessment(db, check, user_id=user.id, tenant_id=user.tenant_id, privileged=requires_mfa(permissions))
        risk_context = {
            "score": assessment.score, "reasons": assessment.reasons, "weights": assessment.weights, "level": assessment.level,
            "known_device": known is not None,
        }
        needs_verification = (
            known is None and risk.enforcing()
            and (check.force_verification or assessment.level in (risk.MODERATE, risk.HIGH, risk.CRITICAL))
        )
        current_user = build_current_user(db, user)
        has_factor = self.mfa_service.has_factor(db, user.id)
        if deny_without_smtp and not has_factor:
            events.record(
                ctx=ctx,
                event_type="login.password", outcome="blocked", user_id=user.id, tenant_id=user.tenant_id, subject_hash=check.subject,
                device_hash=device_hash, risk_score=assessment.score, risk_reasons=assessment.reasons, risk_weights=assessment.weights, enforcement="deny",
                details={"reason": "verification_unavailable"},
            )
            raise _login_denied()
        if needs_verification and not has_factor and smtp:
            # Versand gestört (notifications/delivery_status.py): gar nicht erst versuchen, sondern
            # sofort klar melden - höchstens ein Login je Minute versucht es echt (Erholung).
            if delivery_status.login_blocked(db):
                events.record(
                    ctx=ctx,
                    event_type="login.password", outcome="blocked", user_id=user.id, tenant_id=user.tenant_id, subject_hash=check.subject,
                    device_hash=device_hash, risk_score=assessment.score, risk_reasons=assessment.reasons, risk_weights=assessment.weights, enforcement="email_code",
                    details={"reason": "email_unavailable"},
                )
                raise email_challenge.email_unavailable()
            try:
                ticket = email_challenge.start(db, user=user, request_host=request_host, context=risk_context)
            except email_challenge.ChallengeUnavailable:
                # Erwartet und bereits erfasst (Versandstatus + gedrosseltes Fehlerprotokoll in
                # email_challenge._send) - nicht je Anmeldung nochmals über den HTTPException-Handler.
                events.record(
                    ctx=ctx,
                    event_type="login.password", outcome="blocked", user_id=user.id, tenant_id=user.tenant_id, subject_hash=check.subject,
                    device_hash=device_hash, risk_score=assessment.score, risk_reasons=assessment.reasons, risk_weights=assessment.weights, enforcement="email_code",
                    details={"reason": "email_unavailable"},
                )
                raise email_challenge.email_unavailable() from None  # erwartet, schon in email_challenge._send erfasst
            events.record(
                ctx=ctx,
                event_type="login.password", outcome="challenged", user_id=user.id, tenant_id=user.tenant_id, subject_hash=check.subject,
                device_hash=device_hash, risk_score=assessment.score, risk_reasons=assessment.reasons, risk_weights=assessment.weights, enforcement="email_code",
            )
            return LoginResponse(authenticated=False, mfa=MfaPendingLoginRead(
                status="email_verification_required", ticket=ticket, required=True, user_display_name=user.display_name,
                user_email=user.email, tenant_name=current_user.current_tenant_name, available_methods=[],
                can_add_totp=False, can_add_passkey=False,
            ))
        events.record(
            ctx=ctx,
            event_type="login.password", outcome="success", user_id=user.id, tenant_id=user.tenant_id, subject_hash=check.subject,
            device_hash=device_hash, risk_score=assessment.score, risk_reasons=assessment.reasons, risk_weights=assessment.weights,
            enforcement=("mfa" if has_factor else "none") if risk.enforcing() else "monitor",
        )

        pending_mfa = self.mfa_service.prepare_login(
            db,
            user=user,
            current_user=current_user,
            request_host=request_host,
            risk_context=risk_context,
        )
        if pending_mfa is not None:
            return LoginResponse(authenticated=False, mfa=pending_mfa)

        return self._finish_login(db, response, user=user, request_host=request_host, mfa_verified=False, request=request, amr=["pwd"], risk_context=risk_context)

    def verify_email_challenge(self, db: Session, response: Response, payload: EmailChallengeVerifyRequest, request: Request | None = None) -> LoginResponse:
        """E-Mail-Code bestanden: weiter wie nach dem Passwort (Ersteinrichtung des Faktors bei
        Pflicht, sonst Session)."""
        user, data = email_challenge.verify(db, ticket=payload.ticket, code=payload.code)
        risk_context = {**(data.get("context") or {}), "verified": "email"}
        current_user = build_current_user(db, user)
        pending_mfa = self.mfa_service.prepare_login(db, user=user, current_user=current_user, request_host=data.get("request_host"), risk_context=risk_context)
        if pending_mfa is not None:
            return LoginResponse(authenticated=False, mfa=pending_mfa)
        return self._finish_login(db, response, user=user, request_host=data.get("request_host"), mfa_verified=False, request=request, amr=["pwd", "email"], risk_context=risk_context)

    def resend_email_challenge(self, db: Session, ticket: str) -> None:
        email_challenge.resend(db, ticket)

    def logout(self, db: Session, response: Response, user: CurrentUser | None, request: Request | None = None, *, everywhere: bool = False) -> dict[str, str]:
        """Nur diese Session (samt Kind-Sessions auf Mandanten-Domains) bzw. mit ``everywhere``
        alle Sessions des Kontos. Tokens ohne Session-ID (vor dem Update ausgestellt) lassen sich
        nicht einzeln beenden - dann wie bisher alle (session_revoke_at)."""
        clear_session_cookies(response)
        if user is None:
            return {"message": "Logged out"}
        db_user = db.get(AppUser, user.user_id)
        if db_user is None:
            return {"message": "Logged out"}
        if everywhere or user.session_id is None:
            db_user.session_revoke_at = datetime.now(timezone.utc)
            session_register.revoke_all(db, user.user_id, reason="logout_all" if everywhere else "logout_legacy")
        else:
            session_register.revoke(db, [user.session_id], reason="logout")
        db.add(db_user)
        db.commit()
        events.record(event_type="session.logout", outcome="success", user_id=user.user_id, tenant_id=user.current_tenant_id,
                      session_id=user.session_id, details={"scope": "all" if everywhere or user.session_id is None else "this"})
        _audit.log(db, action="user.logout", actor=user, details={"everywhere": everywhere})
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
        confirmation page (MAIN-SEC-006) - a link alone no longer logs anybody in.

        Die neue Session ist ein Kind der Ausgangs-Session (Logout-Kaskade, SEC-AUTH-011); ist
        diese inzwischen beendet, gilt das Token nicht mehr."""
        bridge = domain_bridge_service.consume_bridge_token(token, request_host)
        if bridge is None:
            count_invalid_token(request_context.current().ip)
            return False

        user = db.get(AppUser, bridge.user_id)
        if not self._may_use_bridge(user):
            return False
        parent = None
        if bridge.parent_sid:
            parent = session_register.validate(db, bridge.parent_sid, user.id)
            if parent is None:
                return False
        elif not bridge.legacy:
            # Ohne Eltern-Session keine neue Session (Security-Review H1); nur v3-Tokens von vor
            # dem Update (Ablauf 120 s) werden noch eingelöst.
            return False
        ctx = request_context.current()
        record = session_register.create(
            db, user_id=user.id, tenant_id=user.tenant_id, mfa=bridge.mfa_verified, amr=["bridge"], parent_id=parent.id if parent else None,
            device_id=parent.device_id if parent else None, host=request_host, ip_net_hash=ctx.net_hash, user_agent_family=ctx.user_agent_family,
            country=ctx.country,
            # Ende der Eltern-Session, nie verlängert; v3-Altlast: wie die bisherigen Tokens
            expires_at=parent.expires_at if parent else datetime.now(timezone.utc) + timedelta(hours=settings.auth_session_ttl_hours),
        )
        # Frische der Eltern-Session übernehmen; v3-Altlast gilt nie als frisch (Step-up nötig)
        record.auth_time = parent.auth_time if parent is not None else datetime.now(timezone.utc) - timedelta(days=1)
        db.commit()
        issue_session_cookie(response, bridge.user_id, mfa_verified=bridge.mfa_verified, sid=str(record.id), expires_at=record.expires_at)
        issue_locale_cookie(response, user.preferred_language)
        return True

    def verify_login_totp(
        self, db: Session, response: Response, payload: TotpLoginVerifyRequest, request: Request | None = None
    ) -> LoginResponse:
        context = self.mfa_service.verify_login_totp(db, ticket=payload.ticket, code=payload.code)
        return self._finish_login(
            db,
            response,
            user=context.user,
            request_host=context.request_host,
            mfa_verified=True,
            request=request,
            amr=["pwd", "totp"],
            risk_context=context.risk_context,
        )

    def start_login_totp_setup(self, db: Session, payload: MfaTicketRequest) -> TotpEnrollmentStartRead:
        return self.mfa_service.start_login_totp_enrollment(db, payload.ticket)

    def complete_login_totp_setup(
        self,
        db: Session,
        response: Response,
        payload: TotpEnrollmentComplete,
        request: Request | None = None,
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
            request=request,
            amr=["pwd", "totp"],
            risk_context=context.risk_context,
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
        request: Request | None = None,
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
            request=request,
            amr=["pwd", "passkey"],
            risk_context=context.risk_context,
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
        request: Request | None = None,
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
            request=request,
            amr=["pwd", "passkey"],
            risk_context=context.risk_context,
        )

    def skip_invite_mfa_setup(self, db: Session, response: Response, payload: MfaSkipRequest, request: Request | None = None) -> LoginResponse:
        """Erstlogin ohne Pflicht: bewusst ohne zweiten Faktor anmelden (MfaService.skip_invite_setup)."""
        context = self.mfa_service.skip_invite_setup(db, payload.ticket)
        return self._finish_login(
            db,
            response,
            user=context.user,
            request_host=context.request_host,
            mfa_verified=False,
            request=request,
            amr=["pwd"],
            risk_context=context.risk_context,
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
            read_only_features=sorted(user.current_tenant_read_only_features),
            finance_currency=user.current_tenant_currency,
            require_mfa=user.tenant_require_mfa,
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
                protocol_wheel_enabled=user.protocol_wheel_enabled,
            ),
            current_tenant=current_tenant,
            permissions=sorted(user.permissions),
            assigned_only=sorted(user.assigned_only),
            roles=[RoleRef(id=role.public_id, name=role.name, system_key=role.system_key) for role in user.roles],
            mfa_grace_until=user.mfa_grace_until,
        )

    def _finish_login(
        self,
        db: Session,
        response: Response,
        *,
        user: AppUser,
        request_host: str | None,
        mfa_verified: bool,
        request: Request | None = None,
        amr: list[str] | None = None,
        risk_context: dict | None = None,
    ) -> LoginResponse:
        """Session ausstellen: Gerät merken (SEC-AUTH-006), Session-Register (SEC-AUTH-011),
        Ereignis ``login.success`` und Sicherheitsmails (neues Gerät, verdächtig, nach Sperre)."""
        first_login = user.first_login_at is None
        if first_login:
            # Ab jetzt ein bestehendes Konto: wird MFA später Pflicht, gilt die 3-Tage-Frist
            # (Migration 0192, app.core.mfa_policy.mfa_grace_until)
            user.first_login_at = datetime.now(timezone.utc)
            db.add(user)
        ctx = request_context.current()
        risk_context = risk_context or {}
        presented = devices.device_id_from_request(request)
        known_before = devices.known_device(db, user.id, presented) is not None
        # Gerät dem Konto unbekannt: immer eine neue Geräte-ID (Security-Review M4) - eine
        # mitgebrachte (z. B. untergeschobene) ID wird nie an ein weiteres Konto gebunden.
        device_id = presented if known_before and presented else devices.new_device_id()
        had_other_devices = bool(db.scalar(select(exists().where(
            AuthKnownDevice.user_id == user.id, AuthKnownDevice.revoked_at.is_(None),
            AuthKnownDevice.device_hash != devices.device_hash(device_id),
        ))))
        device, _created = devices.remember(
            db, user_id=user.id, tenant_id=user.tenant_id, device_id=device_id, user_agent_family=ctx.user_agent_family, country=ctx.country,
        )
        record = session_register.create(
            db, user_id=user.id, tenant_id=user.tenant_id, mfa=mfa_verified, amr=amr or ["pwd"], device_id=device.id,
            host=request_host, ip_net_hash=ctx.net_hash, user_agent_family=ctx.user_agent_family, country=ctx.country,
        )
        level = risk_context.get("level")
        reasons = list(risk_context.get("reasons") or [])
        # Hinweis «neues Gerät» erst, wenn das Konto schon andere Geräte kennt - sonst bekäme nach
        # dem Update jede Person bei der ersten Anmeldung eine Mail.
        if not known_before and had_other_devices and not first_login:
            notify.new_device(db, user, device_hash=device.device_hash, device=ctx.user_agent_family, country=ctx.country)
        if level in (risk.HIGH, risk.CRITICAL):
            notify.suspicious_login(db, user, net_hash=ctx.net_hash, device=ctx.user_agent_family, reasons=reasons, country=ctx.country)
        if pop_locked(user.id):
            notify.login_after_lockout(db, user, device=ctx.user_agent_family, country=ctx.country)
        db.commit()
        if response is not None:
            devices.set_cookie(response, device_id)
        current_user = build_current_user(db, user, mfa_verified=mfa_verified)
        current_user.session_id = record.id
        current_user.auth_time = record.auth_time
        issue_session_cookie(response, user.id, mfa_verified=mfa_verified, sid=str(record.id), expires_at=record.expires_at)
        issue_locale_cookie(response, user.preferred_language)
        events.record(
            event_type="login.success", outcome="success", user_id=user.id, tenant_id=user.tenant_id, device_hash=device.device_hash,
            session_id=record.id, risk_score=risk_context.get("score"), risk_reasons=reasons,
            risk_weights=risk_context.get("weights") if isinstance(risk_context.get("weights"), dict) else None,
            enforcement=str(risk_context.get("verified") or ("mfa" if mfa_verified else "none")),
            details={"known_device": known_before, "new_device": not known_before, "method": "+".join(amr or ["pwd"])},
        )
        _audit.log(db, action="user.login", actor=current_user)
        bridge_redirect_url = domain_bridge_service.resolve_bridge_redirect(
            db,
            request_host,
            user.id,
            current_user.current_tenant_id,
            mfa_verified=mfa_verified,
            parent_sid=str(record.id),
        )
        return LoginResponse(**self.session(current_user, response, bridge_redirect_url).model_dump(), mfa=None)
