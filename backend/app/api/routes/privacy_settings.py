"""Datenschutz-Einstellungen eines Mandanten (Mandanten-Einstellungen → Datenschutz).

Nur Mandanten-Admins. Jede Änderung landet im audit_log.
- statistics_per_person_public: Bussen und Anwesenheit je Person in der Statistik für alle Mitglieder
  sichtbar. Standard aus - dann sehen Leser dort nur sich selbst (Datenschutz-Audit PRIV-001).
- privacy_notice_url: Datenschutzhinweise des Vereins; die Abgabebox verlinkt sie vor dem Upload
  (Datenschutz-Audit E2). Leer = Plattform-Standard (ABGABEBOX_DEFAULT_PRIVACY_URL).
"""
from __future__ import annotations

from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.permissions import P
from app.core.security import CurrentUser, get_current_user, require_permission
from app.models import Tenant
from app.services.audit_service import AuditService

router = APIRouter()
audit = AuditService()


class PrivacySettingsRead(BaseModel):
    statistics_per_person_public: bool
    privacy_notice_url: str | None = None


class PrivacySettingsWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statistics_per_person_public: bool | None = None
    # "" entfernt den Link
    privacy_notice_url: str | None = Field(default=None, max_length=500)

    @field_validator("privacy_notice_url")
    @classmethod
    def _https_only(cls, value: str | None) -> str | None:
        if value is None or value.strip() == "":
            return value
        value = value.strip()
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.hostname or any(ch.isspace() for ch in value):
            raise ValueError("Link muss mit https:// beginnen")
        return value


def _tenant(db: Session, user: CurrentUser) -> Tenant:
    tenant = db.get(Tenant, user.current_tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


def _read(tenant: Tenant) -> PrivacySettingsRead:
    return PrivacySettingsRead(statistics_per_person_public=tenant.statistics_per_person_public, privacy_notice_url=tenant.privacy_notice_url)


@router.get("/privacy-settings", response_model=PrivacySettingsRead)
def get_privacy_settings(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_permission(user, P.SETTINGS_MANAGE)
    return _read(_tenant(db, user))


@router.patch("/privacy-settings", response_model=PrivacySettingsRead)
def update_privacy_settings(body: PrivacySettingsWrite, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_permission(user, P.SETTINGS_MANAGE)
    tenant = _tenant(db, user)
    changes = body.model_dump(exclude_none=True)
    if "statistics_per_person_public" in changes:
        tenant.statistics_per_person_public = changes["statistics_per_person_public"]
    if "privacy_notice_url" in changes:
        tenant.privacy_notice_url = changes["privacy_notice_url"] or None
    audit.log(db, action="privacy_settings.updated", actor=user, entity_type="tenant", entity_id=tenant.id, details=changes)
    db.commit()
    return _read(tenant)
