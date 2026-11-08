"""Spezialfelder der Termine: Alias und Ausblenden je Mandant (Mandanten-Einstellungen)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.permissions import P
from app.core.security import CurrentUser, get_current_user, require_permission
from app.models.entities import Tenant
from app.schemas.event_field_config import EventFieldConfig
from app.services.audit_service import AuditService

router = APIRouter()
audit = AuditService()


@router.get("/event-field-config", response_model=EventFieldConfig)
def get_event_field_config(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    # Jede Termin-Ansicht braucht die Namen; lesen darf, wer Termine sieht
    require_permission(user, P.MEETINGS_READ)
    tenant = db.get(Tenant, user.current_tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return EventFieldConfig.from_stored(tenant.event_field_config_json)


@router.put("/event-field-config", response_model=EventFieldConfig)
def put_event_field_config(payload: EventFieldConfig, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_permission(user, P.SETTINGS_MANAGE)
    tenant = db.get(Tenant, user.current_tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    tenant.event_field_config_json = payload.model_dump()
    db.commit()
    audit.log(db, action="tenant.event_field_config_updated", actor=user, entity_type="tenant", entity_id=tenant.id)
    return EventFieldConfig.from_stored(tenant.event_field_config_json)
