"""Plattform-Admin: Anmeldeschutz (Auth-Audit 2026-11-20) - Daten für das Sicherheits-Dashboard
(zweiter Schritt) und Verwaltung der IP-Sperren (Stufe 5, Entsperren).

Lesen: jeder Plattform-Admin. Sperren setzen/aufheben: require_admin_write, auditiert. Adressen
erscheinen nie im Klartext - nur gekürzte Pseudonyme; eine manuelle Sperre per IP wird beim Setzen
gehasht."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth_security import blocks, read_service
from app.core.admin_security import CurrentAdmin, get_current_admin, require_admin_write
from app.core.admin_step_up import require_step_up
from app.core.db import get_db
from app.schemas.base import MAX_QUERY_OFFSET
from app.services.audit_service import AuditService

router = APIRouter(dependencies=[Depends(get_current_admin)])
audit = AuditService()


class BlockCreate(BaseModel):
    ip: str | None = Field(default=None, max_length=64)
    subject: str | None = Field(default=None, max_length=64)
    scope: Literal["source", "net"] = "source"
    minutes: int = Field(ge=1, le=blocks.MAX_MANUAL_MINUTES)
    reason: str = Field(min_length=3, max_length=200)


@router.get("/auth-security/summary")
def auth_security_summary(db: Session = Depends(get_db)):
    return read_service.platform_summary(db)


@router.get("/auth-security/events")
def auth_security_events(
    db: Session = Depends(get_db),
    event_type: str | None = Query(None, max_length=64),
    outcome: Literal["success", "failure", "blocked", "challenged", "info"] | None = None,
    offset: int = Query(0, ge=0, le=MAX_QUERY_OFFSET),
    limit: int = Query(100, ge=1, le=500),
):
    return read_service.recent_events(db, limit=limit, offset=offset, event_type=event_type, outcome=outcome)


@router.get("/auth-security/blocks")
def auth_security_blocks():
    return read_service.active_blocks()


@router.post("/auth-security/blocks", status_code=201, dependencies=[Depends(require_step_up("platform-settings"))])
def create_block(payload: BlockCreate, db: Session = Depends(get_db), admin: CurrentAdmin = Depends(require_admin_write)):
    if not payload.ip and not payload.subject:
        raise HTTPException(status_code=422, detail="ip oder subject angeben")
    try:
        block = blocks.set_manual(ip=payload.ip, subject=payload.subject, scope=payload.scope, minutes=payload.minutes, reason=payload.reason, admin_id=admin.admin_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    audit.log(db, action="admin.auth_block_set", actor_email=admin.email, details={"scope": block.scope, "minutes": payload.minutes, "reason": block.reason})
    return {"subject": block.subject, "until": block.until}


@router.delete("/auth-security/blocks/{subject}", status_code=204, dependencies=[Depends(require_step_up("platform-settings"))])
def delete_block(subject: str, db: Session = Depends(get_db), admin: CurrentAdmin = Depends(require_admin_write)):
    if len(subject) > 64 or not blocks.clear(subject, admin_id=admin.admin_id):
        raise HTTPException(status_code=404, detail="Sperre nicht gefunden")
    audit.log(db, action="admin.auth_block_cleared", actor_email=admin.email, details={"subject": subject[:12]})
    return Response(status_code=204)
