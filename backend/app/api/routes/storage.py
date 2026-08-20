from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import CurrentUser, get_current_user, require_admin
from app.schemas.storage import StorageUsageRead
from app.services.storage_service import StorageService

router = APIRouter()
service = StorageService()


@router.get("/storage/usage", response_model=StorageUsageRead)
def get_storage_usage(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    """Speicherverbrauch des aktuellen Mandanten mit Aufteilung nach Kategorie - nur fuer den
    Mandanten-Admin sichtbar, analog zu den anderen "Administration"-Seiten (Benutzer,
    Mandant-Einstellungen)."""
    require_admin(user)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    return service.breakdown_for_tenant(db, user.current_tenant_id)
