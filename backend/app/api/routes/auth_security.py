"""Anmeldeaktivität der eigenen Organisation (Daten für das Vereins-Dashboard, zweiter Schritt).

Nur ``access.manage``, nur eigene Konten (tenant_id-Filter und RLS), datensparsam: keine
Netz-/Geräte-Pseudonyme, keine IP, Risiko nur als Klasse."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth_security import read_service
from app.core.db import get_db
from app.core.permissions import P
from app.core.security import CurrentUser, get_current_user, require_permission

router = APIRouter()


@router.get("/auth-security/activity")
def tenant_login_activity(
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_permission(user, P.ACCESS_MANAGE)
    return {
        "summary": read_service.tenant_summary(db, user.current_tenant_id),
        "accounts": read_service.tenant_accounts(db, user.current_tenant_id),
        "events": read_service.tenant_events(db, user.current_tenant_id, limit=limit),
    }
