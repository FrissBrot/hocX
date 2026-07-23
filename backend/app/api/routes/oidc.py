from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import CurrentUser, get_current_user, issue_session_cookie, require_admin
from app.schemas.oidc import OidcConfigPublic, OidcConfigRead, OidcConfigWrite
from app.services.oidc_service import OidcService

router = APIRouter()
service = OidcService()


@router.get("/auth/oidc/public-config/{tenant_id}", response_model=OidcConfigPublic)
def get_public_config(tenant_id: int, db: Session = Depends(get_db)):
    """Public endpoint — returns whether OIDC is enabled for a tenant (no secrets)."""
    return service.get_public_config(db, tenant_id)


@router.get("/auth/oidc/authorize")
def authorize(
    tenant_id: int,
    request: Request,
    redirect_to: str = "/",
    db: Session = Depends(get_db),
):
    """Redirect to OIDC provider authorization endpoint."""
    base = str(request.base_url).rstrip("/")
    url = service.build_authorize_url(db, tenant_id, base, redirect_to)
    return RedirectResponse(url, status_code=302)


@router.get("/auth/oidc/callback")
def callback(
    code: str,
    state: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Handle OIDC provider callback, set session cookie, redirect to frontend."""
    base = str(request.base_url).rstrip("/")
    redirect_to, user_id, tenant_id = service.handle_callback(db, code, state, base, request_host=request.url.hostname)
    # Cookie must be set directly on the returned Response - see handle_callback's docstring.
    redirect = RedirectResponse(url=redirect_to, status_code=302)
    issue_session_cookie(redirect, user_id, tenant_id)
    return redirect


# ── Admin config management ───────────────────────────────────────────────────

@router.get("/tenants/{tenant_id}/oidc-config", response_model=OidcConfigRead)
def get_oidc_config(
    tenant_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_admin(user)
    cfg = service.get_config(db, tenant_id)
    if cfg is None:
        return OidcConfigRead(tenant_id=tenant_id, enabled=False, auto_redirect=False, issuer_url="", client_id="", scopes="openid email profile")
    return cfg


@router.put("/tenants/{tenant_id}/oidc-config", response_model=OidcConfigRead)
def upsert_oidc_config(
    tenant_id: int,
    payload: OidcConfigWrite,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_admin(user)
    return service.upsert_config(db, tenant_id, payload)
