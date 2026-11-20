"""Zugangslinks-Übersicht für Vereins-Admins (Mandant-Einstellungen › Zugangslinks): alle gerade
gültigen Wege, über die jemand ohne Anmeldung an Daten des Vereins kommt (app/public_links)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.permissions import P
from app.core.security import CurrentUser, get_current_user, require_permission
from app.public_links import collect_all, partner_history
from app.schemas.public_links import PartnerHistoryRead, PublicLinkRead

router = APIRouter()


@router.get("/public-links", response_model=list[PublicLinkRead])
def list_public_links(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_permission(user, P.SETTINGS_MANAGE)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    return [PublicLinkRead(**link.__dict__) for link in collect_all(db, user.current_tenant_id)]


@router.get("/public-links/partner-history", response_model=list[PartnerHistoryRead])
def list_partner_history(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    """Verlauf der Partner-Organisationen (Reiter Partner-Organisationen): nur Alben des eigenen
    Mandanten, Partner nur als Organisationsname, ohne IP- und E-Mail-Adressen."""
    require_permission(user, P.SETTINGS_MANAGE)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    return [PartnerHistoryRead(**entry.__dict__) for entry in partner_history.collect(db, user.current_tenant_id)]
