"""Datenschutz-Einstellungen eines Mandanten (Mandanten-Einstellungen → Datenschutz).

Nur Mandanten-Admins. Jede Änderung landet im audit_log.
- statistics_per_person_public: Bussen und Anwesenheit je Person in der Statistik für alle Mitglieder
  sichtbar. Standard aus - dann sehen Leser dort nur sich selbst (Datenschutz-Audit PRIV-001).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import CurrentUser, get_current_user, require_admin
from app.models import Tenant
from app.services.audit_service import AuditService

router = APIRouter()
audit = AuditService()


class PrivacySettingsRead(BaseModel):
    statistics_per_person_public: bool


class PrivacySettingsWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statistics_per_person_public: bool | None = None


def _tenant(db: Session, user: CurrentUser) -> Tenant:
    tenant = db.get(Tenant, user.current_tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


def _read(tenant: Tenant) -> PrivacySettingsRead:
    return PrivacySettingsRead(statistics_per_person_public=tenant.statistics_per_person_public)


@router.get("/privacy-settings", response_model=PrivacySettingsRead)
def get_privacy_settings(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_admin(user)
    return _read(_tenant(db, user))


@router.patch("/privacy-settings", response_model=PrivacySettingsRead)
def update_privacy_settings(body: PrivacySettingsWrite, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_admin(user)
    tenant = _tenant(db, user)
    changes = body.model_dump(exclude_none=True)
    if "statistics_per_person_public" in changes:
        tenant.statistics_per_person_public = changes["statistics_per_person_public"]
    audit.log(db, action="privacy_settings.updated", actor=user, entity_type="tenant", entity_id=tenant.id, details=changes)
    db.commit()
    return _read(tenant)
