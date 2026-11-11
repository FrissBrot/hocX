from urllib.parse import urlencode, urlparse

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.client_ip import client_ip
from app.core.db import SessionLocal, get_db
from app.core.error_log import record_system_error
from app.core.rate_limit import enforce_rate_limit
from app.core.security import CurrentUser, get_optional_current_user
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
from app.services import domain_bridge_service
from app.services.auth_service import AuthService
from app.services.tenant_service import build_tenant_profile_image_url

router = APIRouter()
service = AuthService()


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
def login(payload: LoginRequest, response: Response, request: Request, db: Session = Depends(get_db)):
    return service.login(db, response, payload, request_host=request.url.hostname, client_address=client_ip(request))


@router.post("/mfa/totp/verify", response_model=LoginResponse)
def verify_login_totp(payload: TotpLoginVerifyRequest, response: Response, db: Session = Depends(get_db)):
    return service.verify_login_totp(db, response, payload)


@router.post("/mfa/totp/setup/start", response_model=TotpEnrollmentStartRead)
def start_login_totp_setup(payload: MfaTicketRequest, db: Session = Depends(get_db)):
    return service.start_login_totp_setup(db, payload)


@router.post("/mfa/totp/setup/complete", response_model=LoginResponse)
def complete_login_totp_setup(payload: TotpEnrollmentComplete, response: Response, db: Session = Depends(get_db)):
    return service.complete_login_totp_setup(db, response, payload)


@router.post("/mfa/passkeys/setup/start", response_model=PasskeyRegistrationStartRead)
def start_login_passkey_setup(payload: MfaTicketRequest, request: Request, db: Session = Depends(get_db)):
    return service.start_login_passkey_setup(
        db,
        payload,
        request_host=request.url.hostname,
        request_origin=_expected_origin(request),
    )


@router.post("/mfa/passkeys/setup/complete", response_model=LoginResponse)
def complete_login_passkey_setup(
    payload: PasskeyRegistrationComplete,
    response: Response,
    db: Session = Depends(get_db),
):
    return service.complete_login_passkey_setup(db, response, payload)


@router.post("/mfa/passkeys/assertion/start", response_model=PasskeyAssertionStartRead)
def start_login_passkey_assertion(payload: MfaTicketRequest, request: Request, db: Session = Depends(get_db)):
    return service.start_login_passkey_assertion(
        db,
        payload,
        request_host=request.url.hostname,
        request_origin=_expected_origin(request),
    )


@router.post("/mfa/passkeys/assertion/verify", response_model=LoginResponse)
def verify_login_passkey(
    payload: PasskeyAssertionVerifyRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    return service.verify_login_passkey(db, response, payload)


@router.get("/tenant-by-domain", response_model=TenantByDomainRead)
def tenant_by_domain(domain: str, request: Request, db: Session = Depends(get_db)):
    """Public lookup used by the login page: resolves a tenant's own custom app domain back to
    a tenant id/name so a visitor bounced here from that domain can be auto-selected instead of
    picking their organisation from a dropdown. Deliberately unauthenticated (used pre-login),
    but rate-limited per source IP (audit finding, 2026-08-27) - without a cap this doubled as
    a free domain-enumeration oracle."""
    enforce_rate_limit(f"tenant-by-domain:{client_ip(request)}", limit=20, period_seconds=60)
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
    response: Response,
    db: Session = Depends(get_db),
    user: CurrentUser | None = Depends(get_optional_current_user),
):
    return service.logout(db, response, user)


@router.get("/session", response_model=SessionRead)
def session(request: Request, response: Response, db: Session = Depends(get_db), user: CurrentUser | None = Depends(get_optional_current_user)):
    # bridge_redirect_url is only ever computed for a request on the main domain, for a tenant
    # with a currently-healthy custom domain (see resolve_bridge_redirect) - the frontend is
    # additionally responsible for cooldown-guarding repeated attempts (see
    # frontend/lib/bridge-redirect.ts) so a stale cookie / flapping DNS can't turn this into a
    # redirect loop the way an earlier, unconditional version of this did.
    bridge_redirect_url = None
    if user is not None:
        bridge_redirect_url = domain_bridge_service.resolve_bridge_redirect(
            db,
            request.url.hostname,
            user.user_id,
            user.current_tenant_id,
            mfa_verified=user.mfa_verified,
        )
    return service.session(user, response, bridge_redirect_url)


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
    enforce_rate_limit(f"password-reset-available:{client_ip(request)}", limit=60, period_seconds=60)
    return PasswordResetAvailableRead(enabled=_email_sending_enabled(db))


def _issue_password_reset(email: str) -> None:
    """Läuft nach der Antwort (BackgroundTasks) mit eigener Session: so verrät auch die Antwortzeit
    nicht, ob es das Konto gibt."""
    with SessionLocal() as db:
        try:
            account_links.request_password_reset(db, email)
        except Exception as exc:  # noqa: BLE001 - ausserhalb des Requests: selbst ins Fehlerprotokoll
            db.rollback()
            record_system_error(db, exc=exc)


@router.post("/password-reset/request", status_code=status.HTTP_202_ACCEPTED, response_model=dict[str, str])
def request_password_reset(payload: PasswordResetRequest, request: Request, background: BackgroundTasks, db: Session = Depends(get_db)):
    """Antwortet immer gleich, ob es das Konto gibt oder nicht (kein Orakel). Je Adresse höchstens
    drei Links pro Stunde, damit niemand ein Postfach mit Mails flutet."""
    enforce_rate_limit(f"password-reset-ip:{client_ip(request)}", limit=10, period_seconds=15 * 60)
    email_key = account_links.hash_token(payload.email.strip().lower())
    enforce_rate_limit(f"password-reset-email:{email_key}", limit=3, period_seconds=60 * 60)
    if _email_sending_enabled(db):
        background.add_task(_issue_password_reset, payload.email)
    return {"status": "accepted"}


@router.post("/account-link/preview", response_model=AccountLinkPreviewRead)
def account_link_preview(payload: AccountLinkToken, request: Request, db: Session = Depends(get_db)):
    enforce_rate_limit(f"account-link-ip:{client_ip(request)}", limit=30, period_seconds=15 * 60)
    preview = account_links.preview(db, payload.token)
    if preview is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Der Link ist ungültig oder abgelaufen.")
    return AccountLinkPreviewRead(**preview)


@router.post("/account-link/complete", response_model=AccountLinkCompleteRead)
def account_link_complete(payload: AccountLinkComplete, request: Request, db: Session = Depends(get_db)):
    enforce_rate_limit(f"account-link-ip:{client_ip(request)}", limit=30, period_seconds=15 * 60)
    purpose = account_links.complete(db, payload.token, payload.password)
    return AccountLinkCompleteRead(purpose=purpose)
