from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.admin_security import CurrentAdmin, get_optional_current_admin, issue_admin_session_cookie
from app.core.db import get_db
from app.models import PlatformAdmin
from app.schemas.admin import AdminLoginRequest, AdminSessionRead
from app.schemas.mfa import MfaTicketRequest, TotpEnrollmentComplete, TotpEnrollmentStartRead, TotpLoginVerifyRequest
from app.schemas.oidc import PlatformOidcConfigPublic
from app.services.admin_auth_service import AdminAuthService
from app.services.platform_oidc_service import PlatformOidcService, sanitize_redirect_to

router = APIRouter()
service = AdminAuthService()
oidc_service = PlatformOidcService()


@router.post("/login", response_model=AdminSessionRead)
def login(payload: AdminLoginRequest, response: Response, db: Session = Depends(get_db)):
    return service.login(db, response, payload)


# ── MFA (audit finding, 2026-08-27 - platform admins previously had no MFA option at all) ──
# Ticket-based, unauthenticated-by-session flow, mirroring app/api/routes/auth.py's
# /mfa/totp/* endpoints for tenant users: the admin doesn't have a full session yet at this
# point (login() above always returns a pending ticket, never a session directly), only
# possession of the short-lived ticket from the login response.

@router.post("/mfa/totp/verify", response_model=AdminSessionRead)
def verify_login_totp(payload: TotpLoginVerifyRequest, response: Response, db: Session = Depends(get_db)):
    return service.verify_login_totp(db, response, payload)


@router.post("/mfa/totp/setup/start", response_model=TotpEnrollmentStartRead)
def start_login_totp_setup(payload: MfaTicketRequest, db: Session = Depends(get_db)):
    return service.start_login_totp_setup(db, payload)


@router.post("/mfa/totp/setup/complete", response_model=AdminSessionRead)
def complete_login_totp_setup(payload: TotpEnrollmentComplete, response: Response, db: Session = Depends(get_db)):
    return service.complete_login_totp_setup(db, response, payload)


@router.post("/logout", response_model=dict[str, str])
def logout(
    response: Response,
    db: Session = Depends(get_db),
    admin: CurrentAdmin | None = Depends(get_optional_current_admin),
):
    return service.logout(db, response, admin)


@router.get("/session", response_model=AdminSessionRead)
def session(admin: CurrentAdmin | None = Depends(get_optional_current_admin)):
    return service.session(admin)


# ── SSO (single globally configured provider, admin-panel login only) ───────────────────────

@router.get("/oidc/public-config", response_model=PlatformOidcConfigPublic)
def get_oidc_public_config(db: Session = Depends(get_db)):
    """Unauthenticated - lets the admin login page decide whether to show an SSO button."""
    return oidc_service.get_public_config(db)


@router.get("/oidc/authorize")
def oidc_authorize(request: Request, redirect_to: str = "/", db: Session = Depends(get_db)):
    # Validated again inside build_authorize_url (defense in depth) - sanitizing here too since
    # this route is the first point that ever sees the client-controlled query param.
    base = str(request.base_url).rstrip("/")
    url = oidc_service.build_authorize_url(db, base, sanitize_redirect_to(redirect_to))
    return RedirectResponse(url, status_code=302)


@router.get("/oidc/callback")
def oidc_callback(code: str, state: str, request: Request, db: Session = Depends(get_db)):
    base = str(request.base_url).rstrip("/")
    redirect_to, admin_id = oidc_service.handle_callback(db, code, state, base)
    admin = db.get(PlatformAdmin, admin_id)
    if admin is None or not admin.is_active:
        raise HTTPException(status_code=403, detail="Admin account not available")
    # Cookie must be set directly on the returned Response - see issue_admin_session_cookie /
    # the equivalent customer-facing note in core.security.issue_session_cookie for why.
    # sanitize_redirect_to again here (defense in depth) right before the final redirect.
    redirect = RedirectResponse(url=sanitize_redirect_to(redirect_to), status_code=302)
    # mfa_verified=True: federated SSO through the platform's single configured OIDC
    # provider is treated as already providing equivalent assurance to local TOTP (audit
    # finding, 2026-08-27 only added the local-password-login MFA gate - see
    # admin_security.get_optional_current_admin - not a second, redundant TOTP challenge on
    # top of an org's own IdP-enforced MFA policy). Local password login has no such
    # external factor to lean on, so it goes through AdminMfaService instead.
    issue_admin_session_cookie(redirect, admin.id, mfa_verified=True)
    return redirect
