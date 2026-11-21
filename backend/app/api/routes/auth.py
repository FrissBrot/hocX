from urllib.parse import urlencode, urlparse

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.client_ip import client_ip
from app.core.db import SessionLocal, get_db
from app.core.error_log import record_system_error
from app.core.rate_limit import enforce_rate_limit, within_limit
from app.auth_security import devices
from app.core.security import CurrentUser, get_current_user, get_optional_current_user
from app.schemas.mfa import (
    EmailChallengeVerifyRequest,
    LoginResponse,
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
from app.schemas.user import BridgePreviewRead, BridgeRedeemRequest, LoginRequest, SessionRead, TenantByDomainRead
from app.models import PlatformNotificationSettings
from app.notifications import account as account_links
from app.schemas.notifications import (
    AccountLinkComplete,
    AccountLinkCompleteRead,
    AccountLinkPreviewRead,
    AccountLinkToken,
    PasswordResetAvailableRead,
    PasswordResetRequest,
)
from app.core.permissions import P
from app.services import context_visibility_service, domain_bridge_service
from app.core.auth_pseudonym import normalize_email, source_address
from app.schemas.step_up import EmailChallengeResendRequest, StepUpOptionsRead, StepUpRead, StepUpRequest
from app.services.auth_service import AuthService
from app.services.step_up_service import StepUpService
from app.services.tenant_service import build_tenant_profile_image_url

router = APIRouter()
service = AuthService()
step_up_service = StepUpService()


def _expected_origin(request: Request) -> str:
    # Pinned to the same fixed domain WebAuthn's RP ID uses (see
    # MfaService.rp_id_for_request_host) instead of trusting the client-supplied Origin
    # header back at itself - comparing client_data.origin against a value copied from
    # that same request's own Origin header offered no independent security guarantee
    # (audit finding, 2026-08-25). The RP-ID-hash check remains the primary anchor either
    # way; this closes the origin check's own gap to match it. No settings.traefik_domain
    # (local dev only) still falls back to the request's own host, same as before.
    if settings.traefik_domain:
        return f"https://{settings.traefik_domain}"
    host = request.headers.get("host") or request.url.netloc
    if host.startswith("localhost") or host.startswith("127.0.0.1"):
        return f"http://{host}"
    return f"https://{host}"


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, response: Response, request: Request, background: BackgroundTasks, db: Session = Depends(get_db)):
    return service.login(db, response, payload, request_host=request.url.hostname, client_address=client_ip(request), request=request, background=background)


@router.post("/mfa/totp/verify", response_model=LoginResponse)
def verify_login_totp(payload: TotpLoginVerifyRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    return service.verify_login_totp(db, response, payload, request=request)


@router.post("/challenge/email/verify", response_model=LoginResponse)
def verify_email_challenge(payload: EmailChallengeVerifyRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    """Bestätigungscode per E-Mail (erhöhtes Risiko, Konto ohne zweiten Faktor). Begrenzt je
    Ticket (email_challenge.verify) und je Quelle."""
    enforce_rate_limit(f"email-challenge-ip:{source_address(client_ip(request)).exact}", limit=60, period_seconds=15 * 60)
    return service.verify_email_challenge(db, response, payload, request=request)


@router.post("/challenge/email/resend", response_model=dict[str, str])
def resend_email_challenge(payload: EmailChallengeResendRequest, request: Request, db: Session = Depends(get_db)):
    enforce_rate_limit(f"email-challenge-resend-ip:{source_address(client_ip(request)).exact}", limit=20, period_seconds=15 * 60)
    service.resend_email_challenge(db, payload.ticket)
    return {"status": "sent"}


def _limit_mfa_setup(request: Request) -> None:
    """Einrichtung des zweiten Faktors vor der Anmeldung (Login und Erstlogin über Einladung):
    zusätzlich zu den Grenzen je Ticket/Vorgang je Quell-IP begrenzt (SECURITY-RULES 3.4). Grosszügig,
    weil ein ganzer Verein hinter einer NAT-Adresse gleichzeitig einrichten kann."""
    enforce_rate_limit(f"mfa-setup-ip:{client_ip(request)}", limit=200, period_seconds=15 * 60)


@router.post("/mfa/totp/setup/start", response_model=TotpEnrollmentStartRead)
def start_login_totp_setup(payload: MfaTicketRequest, request: Request, db: Session = Depends(get_db)):
    _limit_mfa_setup(request)
    return service.start_login_totp_setup(db, payload)


@router.post("/mfa/totp/setup/complete", response_model=LoginResponse)
def complete_login_totp_setup(payload: TotpEnrollmentComplete, request: Request, response: Response, db: Session = Depends(get_db)):
    _limit_mfa_setup(request)
    return service.complete_login_totp_setup(db, response, payload, request=request)


@router.post("/mfa/setup/skip", response_model=LoginResponse)
def skip_login_mfa_setup(payload: MfaSkipRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    """Erstlogin über Einladung ohne MFA-Pflicht: «Später einrichten». Bei Pflicht 403."""
    _limit_mfa_setup(request)
    return service.skip_invite_mfa_setup(db, response, payload, request=request)


@router.post("/mfa/passkeys/setup/start", response_model=PasskeyRegistrationStartRead)
def start_login_passkey_setup(payload: MfaTicketRequest, request: Request, db: Session = Depends(get_db)):
    _limit_mfa_setup(request)
    return service.start_login_passkey_setup(
        db,
        payload,
        request_host=request.url.hostname,
        request_origin=_expected_origin(request),
    )


@router.post("/mfa/passkeys/setup/complete", response_model=LoginResponse)
def complete_login_passkey_setup(
    payload: PasskeyRegistrationComplete,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    _limit_mfa_setup(request)
    return service.complete_login_passkey_setup(db, response, payload, request=request)


@router.post("/mfa/passkeys/assertion/start", response_model=PasskeyAssertionStartRead)
def start_login_passkey_assertion(payload: MfaTicketRequest, request: Request, db: Session = Depends(get_db)):
    # Bisher ohne Grenze (Audit 6.1): je Quelle begrenzt, das Konto begrenzt die Prüfung (L6)
    enforce_rate_limit(f"passkey-assertion-ip:{source_address(client_ip(request)).exact}", limit=120, period_seconds=15 * 60)
    return service.start_login_passkey_assertion(
        db,
        payload,
        request_host=request.url.hostname,
        request_origin=_expected_origin(request),
    )


@router.post("/mfa/passkeys/assertion/verify", response_model=LoginResponse)
def verify_login_passkey(
    payload: PasskeyAssertionVerifyRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    return service.verify_login_passkey(db, response, payload, request=request)


@router.get("/tenant-by-domain", response_model=TenantByDomainRead)
def tenant_by_domain(domain: str, request: Request, db: Session = Depends(get_db)):
    """Public lookup used by the login page: resolves a tenant's own custom app domain back to
    a tenant id/name so a visitor bounced here from that domain can be auto-selected instead of
    picking their organisation from a dropdown. Deliberately unauthenticated (used pre-login),
    but rate-limited per source IP (audit finding, 2026-08-27) - without a cap this doubled as
    a free domain-enumeration oracle."""
    enforce_rate_limit(f"tenant-by-domain:{client_ip(request)}", limit=20, period_seconds=60, fail_open=True)
    tenant = domain_bridge_service.resolve_tenant_by_app_domain(db, domain)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown domain")
    return TenantByDomainRead(
        tenant_id=tenant.public_id,
        tenant_name=tenant.name,
        profile_image_url=build_tenant_profile_image_url(tenant.public_id, tenant.profile_image_path),
    )


@router.post("/logout", response_model=dict[str, str])
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    user: CurrentUser | None = Depends(get_optional_current_user),
):
    """Meldet nur diese Session ab (SEC-AUTH-011); «Überall abmelden»: /logout-all."""
    return service.logout(db, response, user, request)


@router.post("/logout-all", response_model=dict[str, str])
def logout_all(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    return service.logout(db, response, user, request, everywhere=True)


# ── Step-up (SEC-AUTH-010) ─────────────────────────────────────────────


def _browser_host(request: Request) -> str | None:
    """Host aus dem Origin-Header (die /api-Weiterleitung des Frontends überschreibt Host)."""
    origin = request.headers.get("origin")
    return urlparse(origin).hostname if origin else request.url.hostname


@router.get("/step-up", response_model=StepUpOptionsRead)
def step_up_options(request: Request, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    return step_up_service.options(db, user, _browser_host(request))


@router.post("/step-up/passkey/start", response_model=PasskeyAssertionStartRead)
def step_up_passkey_start(request: Request, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    return step_up_service.start_passkey(db, user, request_host=_browser_host(request), request_origin=_expected_origin(request))


@router.post("/step-up", response_model=StepUpRead)
def step_up(payload: StepUpRequest, request: Request, response: Response, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    return step_up_service.verify(db, response, user, payload, request_host=_browser_host(request))


@router.get("/session", response_model=SessionRead)
def session(request: Request, response: Response, db: Session = Depends(get_db), user: CurrentUser | None = Depends(get_optional_current_user)):
    # bridge_redirect_url is only ever computed for a request on the main domain, for a tenant
    # with a currently-healthy custom domain (see resolve_bridge_redirect) - the frontend is
    # additionally responsible for cooldown-guarding repeated attempts (see
    # frontend/lib/bridge-redirect.ts) so a stale cookie / flapping DNS can't turn this into a
    # redirect loop the way an earlier, unconditional version of this did.
    bridge_redirect_url = None
    # Nur Sessions im Register dürfen eine Kind-Session auf der Mandanten-Domain erzeugen: sie
    # erbt deren Frische und Ende und endet mit ihr (Security-Review H1). Sessions von vor dem
    # Update (ohne sid) bleiben bis zu ihrem Ablauf auf der aktuellen Domain.
    if user is not None and user.session_id is not None:
        bridge_redirect_url = domain_bridge_service.resolve_bridge_redirect(
            db,
            request.url.hostname,
            user.user_id,
            user.current_tenant_id,
            mfa_verified=user.mfa_verified,
            parent_sid=str(user.session_id),
        )
    result = service.session(user, response, bridge_redirect_url)
    if user is not None and user.current_tenant_id is not None and user.can(P.MEETINGS_READ):
        # Menüpunkt «Fotos aus Abgaben» nur, wenn der Verein Abgabe-Dateien freigibt (Phase 5)
        result.shared_submission_photos = context_visibility_service.any_submission_grant(db, user.current_tenant_id)
    return result


@router.get("/bridge")
def bridge(token: str):
    """Cross-domain session handoff, step 1: never logs in by itself any more (MAIN-SEC-006,
    login CSRF via a link with an attacker-minted token). Sends the browser to the
    confirmation page on this same host, which shows whose session it would get and redeems
    the token only after an explicit click (POST below). Relative redirect, no client-controlled
    target - there is no open-redirect surface.

    Neue Links zeigen direkt auf die Bestätigungsseite mit dem Token im URL-Fragment (SEC-019,
    domain_bridge_service.resolve_bridge_redirect); dieser Weg bleibt nur für Links, die vor dem
    Update ausgestellt wurden, und reicht das Token ebenfalls als Fragment weiter."""
    return RedirectResponse(url=f"/auth/bridge#{urlencode({'token': token})}", status_code=307)


@router.post("/bridge/preview", response_model=BridgePreviewRead)
def bridge_preview(payload: BridgeRedeemRequest, request: Request, db: Session = Depends(get_db)):
    """Vorschau für die Bestätigungsseite. POST mit dem Token im Body statt GET mit Query, damit
    es nicht in Access-Logs landet (SEC-019)."""
    preview = service.preview_bridge_token(db, payload.token, request.url.hostname)
    if preview is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Anmeldelink ist ungültig oder abgelaufen")
    return preview


@router.post("/bridge")
def redeem_bridge(payload: BridgeRedeemRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    """Step 2, after the user confirmed: exchanges the one-time token for a session cookie on
    this host. JSON body only (no form posts from foreign sites), and a present Origin header
    must be this host."""
    origin = request.headers.get("origin")
    if origin is not None and urlparse(origin).hostname != request.url.hostname:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Ungültige Herkunft")
    if not service.redeem_bridge_token(db, response, payload.token, request.url.hostname):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Anmeldelink ist ungültig oder abgelaufen")
    return {"status": "ok"}


# ── Passwort vergessen und Einladung (Benachrichtigungen Phase 3, notifications/account.py) ──
# Öffentlich, deshalb je Quell-IP begrenzt (SECURITY-RULES 3.4); Token nur im Body (3.2).


def _email_sending_enabled(db: Session) -> bool:
    row = db.get(PlatformNotificationSettings, 1)
    return bool(row and row.email_enabled and row.smtp_host and row.email_from_address)


@router.get("/password-reset/available", response_model=PasswordResetAvailableRead)
def password_reset_available(request: Request, db: Session = Depends(get_db)):
    enforce_rate_limit(f"password-reset-available:{client_ip(request)}", limit=60, period_seconds=60, fail_open=True)
    from app.notifications import delivery_status

    status_now = delivery_status.read(db)
    return PasswordResetAvailableRead(enabled=status_now.state != "disabled", disturbed=status_now.blocks_login)


def _issue_password_reset(email: str) -> None:
    """Läuft nach der Antwort (BackgroundTasks) mit eigener Session: so verrät auch die Antwortzeit
    nicht, ob es das Konto gibt."""
    with SessionLocal() as db:
        try:
            account_links.request_password_reset(db, email)
        except Exception as exc:  # noqa: BLE001 - ausserhalb des Requests: selbst ins Fehlerprotokoll
            db.rollback()
            record_system_error(db, exc=exc)


# Eigenes Kontingent je bekanntem Gerät der Inhaberin (zusätzlich zum Adress-Kontingent)
PASSWORD_RESET_DEVICE_LIMIT = 3
PASSWORD_RESET_DEVICE_ACCOUNT_LIMIT = 6
_HOUR = 60 * 60


def _issue_password_reset_from_known_device(email: str, device_id: str) -> None:
    """Wie _issue_password_reset, wenn das Adress-Kontingent aufgebraucht ist: sendet nur, wenn das
    Gerät (signiertes Gerätecookie) DIESEM Konto bekannt ist, und dann höchstens
    PASSWORD_RESET_DEVICE_LIMIT-mal pro Stunde je Gerät. Läuft wie dort erst nach der Antwort -
    Kontosuche und Geräteprüfung verraten so weder über Antwort noch Zeit etwas."""
    with SessionLocal() as db:
        try:
            user = account_links.password_reset_account(db, email)
            device = devices.known_device(db, user.id, device_id) if user is not None else None
            if device is None:
                return
            # Sicherheitsereignis (1.5.1): das Adress-Kontingent ist aufgebraucht und die Inhaberin
            # kommt über ihr Gerät - ein Hinweis, dass Fremde für diese Adresse Links anfordern.
            # Gemeldet wird auch, wenn das Gerätekontingent erschöpft ist (blocked).
            if not within_limit(f"password-reset-device:{user.id}|{device.id}", limit=PASSWORD_RESET_DEVICE_LIMIT, period_seconds=_HOUR):
                _record_device_quota_event(user, "blocked", "device_limit")
                return
            # Dach je Konto über alle Geräte (Security-Review): auch viele bekannte Geräte
            # ergeben nicht beliebig viele Mails
            if not within_limit(f"password-reset-device-user:{user.id}", limit=PASSWORD_RESET_DEVICE_ACCOUNT_LIMIT, period_seconds=_HOUR):
                _record_device_quota_event(user, "blocked", "account_limit")
                return
            _record_device_quota_event(user, "info", "address_quota_exhausted")
            account_links.request_password_reset(db, email)
        except Exception as exc:  # noqa: BLE001 - ausserhalb des Requests: selbst ins Fehlerprotokoll
            db.rollback()
            record_system_error(db, exc=exc)


def _record_device_quota_event(user, outcome: str, reason: str) -> None:
    """auth_event «reset.request» mit layer=device (Anmeldeschutz-Ansicht, Export)."""
    from app.auth_security import events as auth_events

    auth_events.record(
        event_type="reset.request", outcome=outcome, user_id=user.id, tenant_id=user.tenant_id,
        details={"layer": "device", "reason": reason},
    )


@router.post("/password-reset/request", status_code=status.HTTP_202_ACCEPTED, response_model=dict[str, str])
def request_password_reset(payload: PasswordResetRequest, request: Request, background: BackgroundTasks, db: Session = Depends(get_db)):
    """Antwortet immer gleich (202), ob es das Konto gibt oder nicht (kein Orakel). Je Quelle höchstens
    10 Anfragen in 15 Minuten (429 trifft nur die anfragende Quelle). Je Adresse werden höchstens
    drei Mails pro Stunde tatsächlich verschickt, und je Adresse und Quelle höchstens drei - darüber
    antwortet die Route weiter mit 202, ohne zu senden (Security-Review M6: kein Mail-Bombing, und
    die Inhaberin bekommt nie 429 wegen fremder Anfragen).

    Ist das Adress- oder das Adress+Quelle-Kontingent aufgebraucht (z. B. durch Fremde), kommt die
    Inhaberin von einem ihrer bekannten Geräte (signiertes Gerätecookie, ``auth_known_device``
    dieses Kontos) trotzdem durch: eigenes Kontingent von drei Mails pro Stunde je Gerät, höchstens
    sechs pro Stunde und Konto über alle Geräte. Ob Konto und Gerät passen, prüft erst die
    Hintergrundaufgabe nach der Antwort - Antwort und Arbeit im Request sind für alle Fälle gleich
    (Signaturprüfung des Cookies immer, keine Datenbankabfrage). Ein fremdes, gefälschtes oder
    einem anderen Konto gehörendes Gerätecookie bekommt kein Zusatzkontingent."""
    source = source_address(client_ip(request)).exact
    enforce_rate_limit(f"password-reset-ip:{source}", limit=10, period_seconds=15 * 60)
    email = normalize_email(payload.email)
    # Immer auswerten (gleiche Arbeit für alle Anfragen), nur die Signatur - keine DB-Abfrage
    device_id = devices.device_id_from_request(request)
    send = within_limit(f"password-reset-email-src:{email}|{source}", limit=3, period_seconds=_HOUR)
    send = send and within_limit(f"password-reset-email:{email}", limit=3, period_seconds=_HOUR)
    if _email_sending_enabled(db):
        if send:
            background.add_task(_issue_password_reset, payload.email)
        elif device_id is not None:
            background.add_task(_issue_password_reset_from_known_device, payload.email, device_id)
    return {"status": "accepted"}


@router.post("/account-link/preview", response_model=AccountLinkPreviewRead)
def account_link_preview(payload: AccountLinkToken, request: Request, db: Session = Depends(get_db)):
    enforce_rate_limit(f"account-link-ip:{client_ip(request)}", limit=30, period_seconds=15 * 60)
    preview = account_links.preview(db, payload.token)
    if preview is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "link_invalid", "message": "Der Link ist ungültig oder abgelaufen."})
    return AccountLinkPreviewRead(**preview)


@router.post("/account-link/complete", response_model=AccountLinkCompleteRead)
def account_link_complete(payload: AccountLinkComplete, request: Request, response: Response, db: Session = Depends(get_db)):
    """Passwort über den Einmal-Link setzen. Einladung (Erstlogin): danach folgt ohne zweites
    Login der zweite Faktor - die Antwort trägt das Login-Ticket (``mfa``, nur im Body) und
    ``mfa_required`` aus ``account_requires_mfa``. Eine Session entsteht hier nie, erst nach
    bestätigtem Faktor bzw. erlaubtem Überspringen über ``/auth/mfa/...``."""
    enforce_rate_limit(f"account-link-ip:{client_ip(request)}", limit=30, period_seconds=15 * 60)
    purpose, user = account_links.complete_for_user(db, payload.token, payload.password)
    if purpose != "invite":
        # Das Gerät, auf dem das Passwort zurückgesetzt wurde, gilt als bekannt (Security-Review M3):
        # sonst bliebe die Inhaberin nach dem Reset (der alle Geräte vergisst) unter einem laufenden
        # Angriff ausgesperrt.
        from app.auth_security.context import current as current_context

        device_id = devices.new_device_id()
        devices.remember(db, user_id=user.id, tenant_id=user.tenant_id, device_id=device_id, user_agent_family=current_context().user_agent_family)
        db.commit()
        devices.set_cookie(response, device_id)
        return AccountLinkCompleteRead(purpose=purpose)
    pending = service.mfa_service.start_invite_setup(db, user=user, request_host=request.url.hostname)
    return AccountLinkCompleteRead(purpose=purpose, mfa=pending, mfa_required=pending.required if pending else None)
