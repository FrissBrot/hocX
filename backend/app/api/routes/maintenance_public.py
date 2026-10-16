"""GET /api/public/maintenance-status - minimaler, öffentlicher Read-only-Status. Funktioniert
auch während voller Wartung (siehe EXEMPT_PREFIXES in maintenance_middleware.py)."""

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.schemas.maintenance import PublicMaintenanceStatus
from app.services import maintenance_service

router = APIRouter()


@router.get("/public/maintenance-status", response_model=PublicMaintenanceStatus)
def maintenance_status(response: Response, db: Session = Depends(get_db)) -> dict:
    # Nie aus einem Cache: die Anmeldeseite soll das Ende der Wartung sofort bemerken.
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return maintenance_service.public_status(db)
