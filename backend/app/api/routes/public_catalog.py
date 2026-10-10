"""Oeffentlicher (unauthentifizierter) Preiskatalog fuer die Landing Page auf der Hauptdomain.
Liefert nur buchbare Plaene - Aenderungen im Adminportal (Preise, Limits, Features,
"Beliebteste Wahl") erscheinen damit ohne Deployment auf der Website. Kein IP-Rate-Limit: der
Abruf kommt serverseitig vom Frontend (eine IP fuer alle Besucher) und ist ein reiner,
kleiner Katalog-Read ohne Enumerations-Risiko."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.schemas.public_catalog import PublicPlanRead
from app.services.admin_tenant_service import AdminTenantService

router = APIRouter()
service = AdminTenantService()


@router.get("/public/plans", response_model=list[PublicPlanRead])
def list_public_plans(db: Session = Depends(get_db)):
    return service.list_public_plans(db)
