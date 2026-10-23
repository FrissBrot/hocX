"""Aufbewahrung (Mandanten-Einstellungen → Aufbewahrung, Datenschutz-Audit G / Paket 8).

Nur Mandanten-Admins. Fristen speichern, Vorschläge ansehen, bestätigen oder verwerfen.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import CurrentUser, get_current_user, require_admin
from app.services import tenant_retention_service as retention
from app.services.audit_service import AuditService

router = APIRouter()


class RetentionPolicyRead(BaseModel):
    submissions_months: int | None = None
    former_members_years: int | None = None
    unlinked_gallery_years: int | None = None
    auto_apply: bool = False


class RetentionPolicyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    submissions_months: int | None = Field(default=None, ge=1, le=240)
    former_members_years: int | None = Field(default=None, ge=1, le=50)
    unlinked_gallery_years: int | None = Field(default=None, ge=1, le=50)
    auto_apply: bool = False


class RetentionProposalRead(BaseModel):
    id: uuid.UUID
    kind: Literal["submission_upload", "former_member", "gallery_image"]
    label: str | None = None
    reference_date: date | None = None
    created_at: datetime


class RetentionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    action: Literal["apply", "dismiss"]


class RetentionDecisionResult(BaseModel):
    applied: int = 0
    dismissed: int = 0
    failed: int = 0
    missing: int = 0


def _policy_read(policy) -> RetentionPolicyRead:
    return RetentionPolicyRead(
        submissions_months=policy.submissions_months, former_members_years=policy.former_members_years,
        unlinked_gallery_years=policy.unlinked_gallery_years, auto_apply=bool(policy.auto_apply),
    )


@router.get("/retention/policy", response_model=RetentionPolicyRead)
def get_retention_policy(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_admin(user)
    return _policy_read(retention.get_policy(db, user.current_tenant_id))


@router.put("/retention/policy", response_model=RetentionPolicyRead)
def update_retention_policy(payload: RetentionPolicyUpdate, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_admin(user)
    policy = retention.save_policy(db, user.current_tenant_id, payload.model_dump())
    AuditService().log(db, action="retention.policy_updated", actor=user, entity_type="tenant", entity_id=user.current_tenant_id, details=payload.model_dump())
    return _policy_read(policy)


@router.get("/retention/proposals", response_model=list[RetentionProposalRead])
def list_retention_proposals(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_admin(user)
    return [
        RetentionProposalRead(id=p.id, kind=p.kind, label=p.label, reference_date=p.reference_date, created_at=p.created_at)
        for p in retention.list_open(db, user.current_tenant_id)
    ]


@router.post("/retention/proposals/refresh", response_model=list[RetentionProposalRead])
def refresh_retention_proposals(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    """Vorschläge sofort berechnen statt auf den nächtlichen Job zu warten (setzt nichts um)."""
    require_admin(user)
    retention.refresh_proposals(db, user.current_tenant_id)
    db.commit()
    return list_retention_proposals(db, user)


@router.post("/retention/proposals/decide", response_model=RetentionDecisionResult)
def decide_retention_proposals(payload: RetentionDecision, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_admin(user)
    return RetentionDecisionResult(**retention.decide(db, user.current_tenant_id, payload.ids, action=payload.action, user_id=user.user_id))
