"""Echtheitsprüfung aus Sicht des Mandanten (Dokumente → Echtheitsprüfung).

- Anzeige von Name und Logo auf der öffentlichen Prüfseite (Standard aus) und Hinweis auf neuere
  Versionen (Standard an). Was die Prüfseite tatsächlich zeigt, entscheidet die View
  document_verification_public (Migration 0117) anhand dieser beiden Schalter.
- Antrag auf Bestätigung der Organisation durch hocX stellen bzw. zurückziehen; bestätigt oder
  abgelehnt wird im Plattform-Admin (routes/admin.py).
- Stand der eigenen Prüf-Domain (Feature verify_domain): eingerichtet wird sie unter Domains,
  hier wird nur angezeigt, ob neue PDFs und die Weiterleitung sie schon verwenden.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.permissions import P
from app.core.security import CurrentUser, get_current_user, require_permission
from app.documents.strings import normalize_language, text
from app.models import Tenant, TenantFeature
from app.services import identity_verification_service as verification
from app.services import verify_domain_service
from app.services.audit_service import AuditService

router = APIRouter()
audit = AuditService()


class VerificationRequestRead(BaseModel):
    status: str
    tenant_name: str
    message: str | None
    requested_at: datetime
    decided_at: datetime | None
    decision_note: str | None


class VerifyDomainRead(BaseModel):
    domain: str
    status: str
    is_healthy: bool
    # Neue PDFs und die Weiterleitung der zentralen Prüfseite verwenden die Domain
    in_use: bool


class DocumentVerificationRead(BaseModel):
    show_identity: bool
    show_newer_version: bool
    tenant_id: uuid.UUID
    tenant_name: str
    has_logo: bool
    verified_at: datetime | None
    revoked_at: datetime | None
    revoked_reason: str | None
    request: VerificationRequestRead | None
    verify_base_url: str
    has_verify_domain_feature: bool
    verify_domain: VerifyDomainRead | None


class DocumentVerificationWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    show_identity: bool | None = None
    show_newer_version: bool | None = None


class VerificationRequestWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str | None = Field(None, max_length=2000)


def _read(db: Session, tenant: Tenant) -> DocumentVerificationRead:
    latest = verification.latest_request(db, tenant.id)
    domain_row = verify_domain_service.verify_domain_row(db, tenant.id)
    return DocumentVerificationRead(
        show_identity=tenant.verify_show_identity,
        show_newer_version=tenant.verify_show_newer_version,
        tenant_id=tenant.public_id,
        tenant_name=tenant.name,
        has_logo=tenant.profile_image_path is not None,
        verified_at=tenant.identity_verified_at,
        revoked_at=tenant.identity_verification_revoked_at,
        revoked_reason=tenant.identity_verification_revoked_reason,
        request=VerificationRequestRead.model_validate(latest, from_attributes=True) if latest is not None else None,
        verify_base_url=verify_domain_service.tenant_verify_base_url(db, tenant.id),
        has_verify_domain_feature=db.scalar(
            select(TenantFeature.id).where(TenantFeature.tenant_id == tenant.id, TenantFeature.feature_code == "verify_domain", TenantFeature.access == "full")
        ) is not None,
        verify_domain=(
            VerifyDomainRead(
                domain=domain_row.domain,
                status=domain_row.status,
                is_healthy=domain_row.is_healthy,
                in_use=verify_domain_service.usable_verify_domain(db, tenant.id) == domain_row.domain,
            )
            if domain_row is not None
            else None
        ),
    )


def _tenant(db: Session, user: CurrentUser) -> Tenant:
    tenant = db.get(Tenant, user.current_tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail=text(normalize_language(user.preferred_language), "apiError.notFound"))
    return tenant


def _state_error(user: CurrentUser, exc: verification.VerificationStateError) -> HTTPException:
    return HTTPException(status_code=409, detail=text(normalize_language(user.preferred_language), str(exc)))


@router.get("/document-verification", response_model=DocumentVerificationRead)
def get_document_verification(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_permission(user, P.MEETINGS_READ)
    return _read(db, _tenant(db, user))


@router.patch("/document-verification", response_model=DocumentVerificationRead)
def update_document_verification(body: DocumentVerificationWrite, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_permission(user, P.SETTINGS_MANAGE)
    tenant = _tenant(db, user)
    changes = body.model_dump(exclude_none=True)
    if "show_identity" in changes:
        tenant.verify_show_identity = changes["show_identity"]
    if "show_newer_version" in changes:
        tenant.verify_show_newer_version = changes["show_newer_version"]
    audit.log(db, action="document_verification.settings_updated", actor=user, details=changes)
    db.commit()
    return _read(db, tenant)


@router.post("/document-verification/request", response_model=DocumentVerificationRead)
def request_identity_verification(body: VerificationRequestWrite, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_permission(user, P.SETTINGS_MANAGE)
    tenant = _tenant(db, user)
    try:
        verification.request_verification(db, tenant, actor=user, message=body.message)
    except verification.VerificationStateError as exc:
        db.rollback()
        raise _state_error(user, exc) from None
    db.commit()
    return _read(db, tenant)


@router.delete("/document-verification/request", response_model=DocumentVerificationRead)
def withdraw_identity_verification(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_permission(user, P.SETTINGS_MANAGE)
    tenant = _tenant(db, user)
    try:
        verification.withdraw_request(db, tenant, actor=user)
    except verification.VerificationStateError as exc:
        db.rollback()
        raise _state_error(user, exc) from None
    db.commit()
    return _read(db, tenant)
