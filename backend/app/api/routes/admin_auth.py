from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.admin_security import CurrentAdmin, get_optional_current_admin, issue_admin_session_cookie
from app.core.db import get_db
from app.models import PlatformAdmin
from app.schemas.admin import AdminLoginRequest, AdminSessionRead
from app.schemas.oidc import PlatformOidcConfigPublic
from app.services.admin_auth_service import AdminAuthService
from app.services.platform_oidc_service import PlatformOidcService

router = APIRouter()
service = AdminAuthService()
oidc_service = PlatformOidcService()


@router.post("/login", response_model=AdminSessionRead)
def login(payload: AdminLoginRequest, response: Response, db: Session = Depends(get_db)):
    return service.login(db, response, payload)


@router.post("/logout", response_model=dict[str, str])
def logout(response: Response):
    return service.logout(response)


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
    base = str(request.base_url).rstrip("/")
    url = oidc_service.build_authorize_url(db, base, redirect_to)
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
    redirect = RedirectResponse(url=redirect_to, status_code=302)
    issue_admin_session_cookie(redirect, admin.id)
    return redirect
