"""Plattform-Admin: Organisationen verifizieren (Abzeichen «Verifizierte Organisation» auf der
öffentlichen Prüfseite). Anträge stellen Mandanten-Admins (routes/document_verification.py);
hier werden sie bestätigt oder abgelehnt, und eine bestehende Bestätigung kann entzogen werden.
Alles im Audit-Log (identity_verification_service)."""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.admin_security import CurrentAdmin, get_current_admin, require_admin_write
from app.core.db import get_db
from app.models import IdentityVerificationRequest, Tenant
from app.models.entities import AppUser, PlatformAdmin
from app.services import identity_verification_service as verification
from app.services import public_id_service

router = APIRouter()


class AdminVerificationRequestRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    current_tenant_name: str
    tenant_name: str
    status: str
    message: str | None
    requested_by_email: str | None
    requested_at: datetime
    decided_at: datetime | None
    decided_by_email: str | None
    decision_note: str | None


class AdminTenantVerificationRead(BaseModel):
    tenant_id: uuid.UUID
    tenant_name: str
    verified_at: datetime | None
    verified_by_email: str | None
    note: str | None
    revoked_at: datetime | None
    revoked_reason: str | None
    show_identity: bool
    requests: list[AdminVerificationRequestRead]


class AdminVerificationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(None, max_length=2000)


def _email(db: Session, model: type, row_id: int | None) -> str | None:
    if row_id is None:
        return None
    row = db.get(model, row_id)
    return getattr(row, "email", None) if row is not None else None


def _request_read(db: Session, row: IdentityVerificationRequest, tenant: Tenant) -> AdminVerificationRequestRead:
    return AdminVerificationRequestRead(
        id=row.public_id,
        tenant_id=tenant.public_id,
        current_tenant_name=tenant.name,
        tenant_name=row.tenant_name,
        status=row.status,
        message=row.message,
        requested_by_email=_email(db, AppUser, row.requested_by),
        requested_at=row.requested_at,
        decided_at=row.decided_at,
        decided_by_email=_email(db, PlatformAdmin, row.decided_by_admin_id),
        decision_note=row.decision_note,
    )


def _tenant_or_404(db: Session, tenant_id: uuid.UUID) -> Tenant:
    tenant = public_id_service.get_by_public_id(db, Tenant, tenant_id)  # nosemgrep: public-id-lookup-without-tenant -- Plattform-Admin-Route (get_current_admin), mandantenübergreifend gewollt
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


def _tenant_read(db: Session, tenant: Tenant) -> AdminTenantVerificationRead:
    rows = db.scalars(
        select(IdentityVerificationRequest)
        .where(IdentityVerificationRequest.tenant_id == tenant.id)
        .order_by(IdentityVerificationRequest.requested_at.desc(), IdentityVerificationRequest.id.desc())
        .limit(20)
    ).all()
    return AdminTenantVerificationRead(
        tenant_id=tenant.public_id,
        tenant_name=tenant.name,
        verified_at=tenant.identity_verified_at,
        verified_by_email=_email(db, PlatformAdmin, tenant.identity_verified_by_admin_id),
        note=tenant.identity_verification_note,
        revoked_at=tenant.identity_verification_revoked_at,
        revoked_reason=tenant.identity_verification_revoked_reason,
        show_identity=tenant.verify_show_identity,
        requests=[_request_read(db, row, tenant) for row in rows],
    )


@router.get("/identity-verification-requests", response_model=list[AdminVerificationRequestRead])
def list_identity_verification_requests(
    status: str = Query("pending", pattern="^(pending|approved|rejected|withdrawn|all)$"),
    db: Session = Depends(get_db),
    _: CurrentAdmin = Depends(get_current_admin),
):
    query = select(IdentityVerificationRequest, Tenant).join(Tenant, Tenant.id == IdentityVerificationRequest.tenant_id)
    if status != "all":
        query = query.where(IdentityVerificationRequest.status == status)
    rows = db.execute(query.order_by(IdentityVerificationRequest.requested_at.asc()).limit(200)).all()
    return [_request_read(db, row, tenant) for row, tenant in rows]


@router.get("/tenants/{tenant_id}/identity-verification", response_model=AdminTenantVerificationRead)
def get_tenant_identity_verification(tenant_id: uuid.UUID, db: Session = Depends(get_db), _: CurrentAdmin = Depends(get_current_admin)):
    return _tenant_read(db, _tenant_or_404(db, tenant_id))


def _decide(db: Session, tenant_id: uuid.UUID, action) -> AdminTenantVerificationRead:
    tenant = _tenant_or_404(db, tenant_id)
    try:
        action(tenant)
    except verification.VerificationStateError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from None
    db.commit()
    return _tenant_read(db, tenant)


@router.post("/tenants/{tenant_id}/identity-verification/approve", response_model=AdminTenantVerificationRead)
def approve_identity_verification(
    tenant_id: uuid.UUID, body: AdminVerificationDecision, db: Session = Depends(get_db), admin: CurrentAdmin = Depends(require_admin_write)
):
    return _decide(db, tenant_id, lambda tenant: verification.approve(db, tenant, admin_id=admin.admin_id, admin_email=admin.email, note=body.note))


@router.post("/tenants/{tenant_id}/identity-verification/reject", response_model=AdminTenantVerificationRead)
def reject_identity_verification(
    tenant_id: uuid.UUID, body: AdminVerificationDecision, db: Session = Depends(get_db), admin: CurrentAdmin = Depends(require_admin_write)
):
    return _decide(db, tenant_id, lambda tenant: verification.reject(db, tenant, admin_id=admin.admin_id, admin_email=admin.email, note=body.note or ""))


@router.post("/tenants/{tenant_id}/identity-verification/revoke", response_model=AdminTenantVerificationRead)
def revoke_identity_verification(
    tenant_id: uuid.UUID, body: AdminVerificationDecision, db: Session = Depends(get_db), admin: CurrentAdmin = Depends(require_admin_write)
):
    def action(tenant: Tenant) -> None:
        if not verification.revoke(db, tenant, admin_email=admin.email, reason=verification.REVOKED_BY_ADMIN, note=body.note):
            raise verification.VerificationStateError("apiError.verificationNotVerified")

    return _decide(db, tenant_id, action)
