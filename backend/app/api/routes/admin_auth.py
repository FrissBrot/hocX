"""Anmeldung am Plattform-Admin-Panel: Passwort, danach ausschliesslich Passkey (WebAuthn).

Seit Migration 0205 gibt es für Admins weder TOTP noch SSO (OIDC). Ein Konto ohne Passkey richtet
nach dem Passwort zwingend einen ein (Trust on first use) und erhält erst danach eine Session.
Alle Routen hier sind ohne Session erreichbar (sie führen zu ihr) - aber wie jede /api/admin-Route
nur über den Admin-Entrypoint (app/core/admin_gate.py).
"""
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.core.admin_origin import admin_request_hostname, expected_admin_origin
from app.core.admin_security import CurrentAdmin, get_optional_current_admin
from app.core.client_ip import client_ip
from app.core.db import get_db
from app.schemas.admin import AdminLoginRequest, AdminSessionRead
from app.schemas.mfa import (
    MfaTicketRequest,
    PasskeyAssertionStartRead,
    PasskeyAssertionVerifyRequest,
    PasskeyRegistrationComplete,
    PasskeyRegistrationStartRead,
)
from app.services.admin_auth_service import AdminAuthService

router = APIRouter()
service = AdminAuthService()


@router.get("/health")
def health() -> dict[str, str]:
    """Erreichbarkeit der Admin-API über den Admin-Entrypoint (deploy.sh/verify_release.sh,
    traefik_checks.sh, Wartungsseite). Ohne Session, ohne Datenbank, gibt nichts preis."""
    return {"status": "ok"}


@router.post("/login", response_model=AdminSessionRead)
def login(payload: AdminLoginRequest, response: Response, request: Request, db: Session = Depends(get_db)):
    return service.login(db, response, payload, client_address=client_ip(request))


@router.post("/mfa/passkey/start", response_model=PasskeyAssertionStartRead)
def start_login_passkey(payload: MfaTicketRequest, request: Request, db: Session = Depends(get_db)):
    return service.start_login_passkey(
        db, ticket=payload.ticket, request_host=admin_request_hostname(request), request_origin=expected_admin_origin(request)
    )


@router.post("/mfa/passkey/verify", response_model=AdminSessionRead)
def verify_login_passkey(payload: PasskeyAssertionVerifyRequest, response: Response, db: Session = Depends(get_db)):
    return service.verify_login_passkey(db, response, flow_token=payload.flow_token, credential=payload.credential)


@router.post("/mfa/passkey/setup/start", response_model=PasskeyRegistrationStartRead)
def start_login_passkey_setup(payload: MfaTicketRequest, request: Request, db: Session = Depends(get_db)):
    return service.start_login_passkey_setup(
        db, ticket=payload.ticket, request_host=admin_request_hostname(request), request_origin=expected_admin_origin(request)
    )


@router.post("/mfa/passkey/setup/complete", response_model=AdminSessionRead)
def complete_login_passkey_setup(payload: PasskeyRegistrationComplete, response: Response, db: Session = Depends(get_db)):
    return service.complete_login_passkey_setup(
        db, response, flow_token=payload.flow_token, label=payload.label, credential=payload.credential
    )


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
