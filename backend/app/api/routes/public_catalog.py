"""Oeffentlicher (unauthentifizierter) Preiskatalog fuer die Landing Page auf der Hauptdomain.
Liefert nur buchbare Plaene - Aenderungen im Adminportal (Preise, Limits, Features,
"Beliebteste Wahl") erscheinen damit ohne Deployment auf der Website. Kein IP-Rate-Limit: der
Abruf kommt serverseitig vom Frontend (eine IP fuer alle Besucher) und ist ein reiner,
kleiner Katalog-Read ohne Enumerations-Risiko. Dasselbe gilt fuer die Kundenliste: nur Namen
von Mandanten, die im Adminportal ausdruecklich fuer die Website freigegeben wurden."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.schemas.public_catalog import PublicCustomerRead, PublicPlanRead
from app.services.admin_tenant_service import AdminTenantService

router = APIRouter()
service = AdminTenantService()


@router.get("/public/plans", response_model=list[PublicPlanRead])
def list_public_plans(db: Session = Depends(get_db)):
    return service.list_public_plans(db)


@router.get("/public/customers", response_model=list[PublicCustomerRead])
def list_public_customers(db: Session = Depends(get_db)):
    return service.list_public_customers(db)
