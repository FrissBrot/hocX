"""Plattform-Admin: Dashboard-Übersicht, Navigationszähler und Ctrl+K-Suche (Admin-Redesign).

Alle Routen: jeder aktive Plattform-Admin (get_current_admin am Router). Felder aus Quellen, die nur
``owner`` lesen darf (Systemstatus, Fehler, Audit, Jobs, Anmeldeereignisse), sind für ``support``
``null`` bzw. fehlen (Suchgruppen). Die Zeitreihen sind nur für ``owner``.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.admin_security import CurrentAdmin, get_current_admin, require_admin_owner
from app.core.db import get_db
from app.core.rate_limit import enforce_rate_limit
from app.services import admin_overview_service
from app.services.audit_service import AuditService

router = APIRouter(dependencies=[Depends(get_current_admin)])
audit = AuditService()

SEARCH_RATE_LIMIT_PER_MINUTE = 60


class AdminSearchRequest(BaseModel):
    q: str = Field(min_length=2, max_length=100)


def _is_owner(admin: CurrentAdmin) -> bool:
    return admin.role == "owner"  # rbac-ok: Plattform-Admin-Rolle (owner/support), kein Mandanten-Rollencode


@router.get("/overview")
def get_overview(db: Session = Depends(get_db), admin: CurrentAdmin = Depends(get_current_admin)):
    return admin_overview_service.overview(db, owner=_is_owner(admin))


@router.get("/overview/series")
def get_overview_series(
    kind: Literal["logins", "errors"],
    range: Literal["24h", "7d", "30d", "90d"] = "24h",  # noqa: A002 - Query-Name laut Plan
    db: Session = Depends(get_db),
    admin: CurrentAdmin = Depends(require_admin_owner),
):
    return admin_overview_service.series(db, kind=kind, range_=range)


@router.get("/nav-counts")
def get_nav_counts(db: Session = Depends(get_db), admin: CurrentAdmin = Depends(get_current_admin)):
    return admin_overview_service.nav_counts(db, owner=_is_owner(admin))


@router.post("/search")
def search(payload: AdminSearchRequest, db: Session = Depends(get_db), admin: CurrentAdmin = Depends(get_current_admin)):
    """POST, damit der Suchbegriff (evtl. eine E-Mail) nicht in URL/Logs landet."""
    enforce_rate_limit(f"admin-search:{admin.admin_id}", limit=SEARCH_RATE_LIMIT_PER_MINUTE, period_seconds=60, fail_open=True)
    groups, users_queried = admin_overview_service.search(db, payload.q, owner=_is_owner(admin))
    if users_queried:
        # Nur die Personensuche wird auditiert - ohne den Begriff selbst.
        audit.log(
            db,
            action="admin.search",
            actor_email=admin.email,
            details={
                "groups": [group["group"] for group in groups],
                "result_count": sum(len(group["items"]) for group in groups),
                "q_len": len(payload.q.strip()),
            },
        )
    return {"groups": groups}
