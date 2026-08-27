import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.security import CurrentUser, get_current_user, get_optional_current_user
from app.models import Tenant
from app.services import public_id_service
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
from app.schemas.user import LoginRequest, SessionRead, TenantByDomainRead
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
    return service.login(db, response, payload, request_host=request.url.hostname)


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
def tenant_by_domain(domain: str, db: Session = Depends(get_db)):
    """Public lookup used by the login page: resolves a tenant's own custom app domain back to
    a tenant id/name so a visitor bounced here from that domain can be auto-selected instead of
    picking their organisation from a dropdown."""
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
def session(request: Request, db: Session = Depends(get_db), user: CurrentUser | None = Depends(get_optional_current_user)):
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
    return service.session(user, bridge_redirect_url)


@router.post("/select-tenant/{tenant_id}", response_model=SessionRead)
def select_tenant(
    tenant_id: uuid.UUID,
    response: Response,
    request: Request,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    internal_id = public_id_service.resolve_internal_id(db, Tenant, tenant_id)
    if internal_id is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return service.select_tenant(db, response, user, internal_id, request_host=request.url.hostname)


@router.get("/bridge")
def bridge(token: str, db: Session = Depends(get_db)):
    """Cross-domain session handoff: exchanges a one-time token (minted by login/select-tenant
    on the main domain) for a session cookie scoped to whichever custom domain this request came
    in on. Never takes a client-controlled redirect target - there is no open-redirect surface."""
    # Cookies must be set directly on the Response object that actually gets returned - FastAPI
    # discards Set-Cookie headers from an injected `Response` dependency the moment the route
    # returns a different Response instance (like RedirectResponse) instead of plain data.
    redirect = RedirectResponse(url="/", status_code=307)
    ok = service.redeem_bridge_token(db, redirect, token)
    if not ok:
        fallback = f"https://{settings.traefik_domain}/login" if settings.traefik_domain else "/"
        return RedirectResponse(url=fallback, status_code=302)
    return redirect
