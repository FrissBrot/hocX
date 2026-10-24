"""Plattform-Admin: System -> Wartung (/admin/maintenance).

Alle mutierenden Aktionen brauchen require_admin_write, werden auditiert und laufen gegen eine
gesperrte Zeile (SELECT ... FOR UPDATE in maintenance_service.lock_window) - ein Doppelklick
oder zwei gleichzeitige Admins können denselben Übergang nicht zweimal auslösen.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.admin_security import CurrentAdmin, get_current_admin, require_admin_write
from app.core.db import get_db
from app.models import MaintenanceEvent, MaintenanceWindow
from app.schemas.maintenance import (
    MaintenanceConditionRead,
    MaintenanceCreate,
    MaintenanceEventRead,
    MaintenanceOverview,
    MaintenanceUpdate,
    MaintenanceWindowRead,
)
from app.services import maintenance_service
from app.services.audit_service import AuditService
from app.services.maintenance_service import BLOCKING_STATES, MaintenanceError

router = APIRouter(dependencies=[Depends(get_current_admin)])
audit = AuditService()


def _read(db: Session, window: MaintenanceWindow, *, with_events: bool = False) -> MaintenanceWindowRead:
    data = MaintenanceWindowRead.model_validate(window)
    if window.state not in maintenance_service.TERMINAL_STATES and window.state != "scheduled":
        data.conditions = [
            MaintenanceConditionRead(key=r.key, satisfied=r.satisfied, reason=r.reason, params=r.params)
            for r in maintenance_service.evaluate_release_conditions(db, window)
        ]
    if with_events:
        events = db.scalars(select(MaintenanceEvent).where(MaintenanceEvent.window_id == window.id).order_by(MaintenanceEvent.id.desc()).limit(200)).all()
        data.events = [MaintenanceEventRead.model_validate(event) for event in events]
    return data


@router.get("/maintenance", response_model=MaintenanceOverview)
def maintenance_overview(
    db: Session = Depends(get_db),
    history_offset: int = Query(0, ge=0),
    history_limit: int = Query(20, ge=1, le=100),
):
    current = db.scalars(select(MaintenanceWindow).where(MaintenanceWindow.state.in_(BLOCKING_STATES)).order_by(MaintenanceWindow.created_at)).all()
    scheduled = db.scalars(select(MaintenanceWindow).where(MaintenanceWindow.state == "scheduled").order_by(MaintenanceWindow.scheduled_start_at)).all()
    history_query = select(MaintenanceWindow).where(MaintenanceWindow.state.in_(maintenance_service.TERMINAL_STATES))
    history = db.scalars(history_query.order_by(MaintenanceWindow.created_at.desc()).offset(history_offset).limit(history_limit)).all()
    total = db.scalar(select(func.count()).select_from(history_query.subquery())) or 0
    return MaintenanceOverview(
        blocking=bool(current),
        full_active=any(window.kind == "full" for window in current),
        current=[_read(db, window, with_events=True) for window in current],
        scheduled=[_read(db, window) for window in scheduled],
        history=[_read(db, window) for window in history],
        history_total=total,
    )


@router.get("/maintenance/{window_id}", response_model=MaintenanceWindowRead)
def get_maintenance_window(window_id: uuid.UUID, db: Session = Depends(get_db)):
    window = db.get(MaintenanceWindow, window_id)
    if window is None:
        raise HTTPException(status_code=404, detail="Wartungsfenster nicht gefunden")
    return _read(db, window, with_events=True)


def _audit(db: Session, admin: CurrentAdmin, action: str, window: MaintenanceWindow, details: dict | None = None) -> None:
    audit.log(db, action=action, actor_email=admin.email, entity_type="maintenance_window", details={"window_id": str(window.id), **(details or {})})


@router.post("/maintenance", response_model=MaintenanceWindowRead, status_code=201)
def create_maintenance(payload: MaintenanceCreate, db: Session = Depends(get_db), admin: CurrentAdmin = Depends(require_admin_write)):
    """Manuelle Wartung planen oder sofort kontrolliert starten. Manuelle Fenster haben keine
    Jobbedingungen - ihre Freigabe prüft trotzdem, dass kein Cutover/Fence offen ist."""
    if payload.start_now and payload.scheduled_start_at is not None:
        raise HTTPException(status_code=422, detail="Entweder sofort starten oder einen Beginn planen")
    if not payload.start_now and payload.scheduled_start_at is None:
        raise HTTPException(status_code=422, detail="Für eine geplante Wartung ist ein Beginn nötig")
    try:
        window = maintenance_service.create_window(
            db,
            kind=payload.kind,
            block_scope="all" if payload.kind == "full" else payload.block_scope,
            reason_code="manual",
            state="preparing" if payload.start_now else "scheduled",
            affected_features=payload.affected_features or None,
            public_message=payload.public_message,
            internal_note=payload.internal_note,
            scheduled_start_at=payload.scheduled_start_at,
            scheduled_end_at=payload.scheduled_end_at,
            release_conditions=[{"key": "storage_not_fenced"}],
            actor_email=admin.email,
        )
        if payload.scheduled_end_at is not None:
            from datetime import UTC, datetime

            # Ein geplantes Ende ist nur eine Ankündigung für die Anmeldeseite - die Freigabe
            # bleibt eine bewusste Admin-Aktion (kein Timer beendet die Wartung).
            start = payload.scheduled_start_at or datetime.now(UTC)
            planned = max(int((payload.scheduled_end_at - start).total_seconds()), 60)
            maintenance_service.apply_estimate(db, window, {
                "scope": "manual", "remaining_low_seconds": planned, "remaining_high_seconds": planned,
                "safety_margin_seconds": 0, "confidence": "planned", "rate_basis": "manual", "reserve_basis": "manual",
            })
    except MaintenanceError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    _audit(db, admin, "admin.maintenance_created", window, {"kind": window.kind, "state": window.state})
    return _read(db, window, with_events=True)


@router.patch("/maintenance/{window_id}", response_model=MaintenanceWindowRead)
def update_maintenance(window_id: uuid.UUID, payload: MaintenanceUpdate, db: Session = Depends(get_db), admin: CurrentAdmin = Depends(require_admin_write)):
    try:
        window = maintenance_service.update_message(
            db, window_id, public_message=payload.public_message, internal_note=payload.internal_note,
            scheduled_start_at=payload.scheduled_start_at, scheduled_end_at=payload.scheduled_end_at, actor_email=admin.email,
        )
    except MaintenanceError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    _audit(db, admin, "admin.maintenance_updated", window)
    return _read(db, window, with_events=True)


@router.post("/maintenance/{window_id}/start", response_model=MaintenanceWindowRead)
def start_maintenance(window_id: uuid.UUID, db: Session = Depends(get_db), admin: CurrentAdmin = Depends(require_admin_write)):
    try:
        window = maintenance_service.start_window(db, window_id, actor_email=admin.email)
    except MaintenanceError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    _audit(db, admin, "admin.maintenance_started", window)
    return _read(db, window, with_events=True)


@router.post("/maintenance/{window_id}/release", response_model=MaintenanceWindowRead)
def release_maintenance(window_id: uuid.UUID, db: Session = Depends(get_db), admin: CurrentAdmin = Depends(require_admin_write)):
    """Wartung beenden - nur nach bestandenen Freigabebedingungen (409 mit Begründung sonst).
    Auch Administratoren können so keine offene Datenmigration oder kein Fence umgehen."""
    try:
        window = maintenance_service.release(db, window_id, actor_email=admin.email, source="admin")
    except MaintenanceError as exc:
        db.commit()  # Ablehnung bleibt im Verlauf stehen
        audit.log(db, action="admin.maintenance_release_rejected", actor_email=admin.email, entity_type="maintenance_window", details={"window_id": str(window_id), "reason": str(exc)})
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    _audit(db, admin, "admin.maintenance_released", window)
    return _read(db, window, with_events=True)


@router.post("/maintenance/{window_id}/cancel", response_model=MaintenanceWindowRead)
def cancel_maintenance(window_id: uuid.UUID, db: Session = Depends(get_db), admin: CurrentAdmin = Depends(require_admin_write)):
    try:
        window = maintenance_service.cancel_scheduled(db, window_id, actor_email=admin.email)
    except MaintenanceError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    _audit(db, admin, "admin.maintenance_cancelled", window)
    return _read(db, window)
