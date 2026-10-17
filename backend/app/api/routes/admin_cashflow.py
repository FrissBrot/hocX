"""Plattform-Admin: Mandanten -> Cashflow (/admin/cashflow).

Lesende Routen erzeugen vorher die fälligen Forderungen (cashflow_service.sync_charges) - das ist
Systempflege, keine Admin-Aktion, und läuft daher auch für Admins mit Leserechten. Alle
Änderungen brauchen require_admin_write und werden auditiert.
"""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.admin_security import CurrentAdmin, get_current_admin, require_admin_write
from app.core.db import get_db
from app.schemas.cashflow import (
    CashflowCostRead,
    CashflowCostStatusUpdate,
    CashflowCostWrite,
    CashflowOverview,
    TenantChargePage,
    TenantChargeRead,
    TenantChargeUpdate,
)
from app.services import cashflow_service
from app.services.audit_service import AuditService

router = APIRouter(dependencies=[Depends(get_current_admin)])
audit = AuditService()


def _sync(db: Session) -> None:
    try:
        cashflow_service.sync_charges(db)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="Forderungen konnten nicht erzeugt werden") from exc


@router.get("/cashflow/overview", response_model=CashflowOverview)
def cashflow_overview(year: int | None = Query(None, ge=2000, le=2100), db: Session = Depends(get_db)):
    _sync(db)
    return cashflow_service.overview(db, year)


@router.get("/cashflow/charges", response_model=TenantChargePage)
def list_charges(
    db: Session = Depends(get_db),
    status: Literal["open", "paid", "waived", "overdue"] | None = None,
    q: str | None = Query(None, max_length=200),
    year: int | None = Query(None, ge=2000, le=2100),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    _sync(db)
    return cashflow_service.list_charges(db, status=status, q=q, year=year, offset=offset, limit=limit)


@router.patch("/cashflow/charges/{charge_id}", response_model=TenantChargeRead)
def update_charge(
    charge_id: uuid.UUID,
    payload: TenantChargeUpdate,
    db: Session = Depends(get_db),
    current_admin: CurrentAdmin = Depends(require_admin_write),
):
    result = cashflow_service.update_charge(db, charge_id, payload)
    if result is None:
        raise HTTPException(status_code=404, detail="Forderung nicht gefunden")
    audit.log(
        db, action="admin.cashflow_charge_updated", actor_email=current_admin.email, entity_type="tenant_charge",
        details={"charge_id": str(charge_id), "status": result.status, "paid_on": result.paid_on.isoformat() if result.paid_on else None},
    )
    return result


@router.post("/cashflow/charges/{charge_id}/recalculate", response_model=TenantChargeRead)
def recalculate_charge(
    charge_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_admin: CurrentAdmin = Depends(require_admin_write),
):
    try:
        result = cashflow_service.recalculate_charge(db, charge_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Forderung nicht gefunden")
    audit.log(
        db, action="admin.cashflow_charge_recalculated", actor_email=current_admin.email, entity_type="tenant_charge",
        details={"charge_id": str(charge_id), "amount_rp": result.amount_rp},
    )
    return result


@router.get("/cashflow/costs", response_model=list[CashflowCostRead])
def list_costs(db: Session = Depends(get_db)):
    return cashflow_service.list_costs(db)


def _audit_cost(db: Session, admin: CurrentAdmin, action: str, cost: CashflowCostRead | uuid.UUID) -> None:
    details = (
        {"cost_id": str(cost)}
        if isinstance(cost, uuid.UUID)
        else {"cost_id": str(cost.id), "name": cost.name, "kind": cost.kind, "status": cost.status, "amount_rp": cost.amount_rp, "percent_bp": cost.percent_bp, "interval": cost.interval}
    )
    audit.log(db, action=action, actor_email=admin.email, entity_type="cashflow_cost", details=details)


@router.post("/cashflow/costs", response_model=CashflowCostRead, status_code=201)
def create_cost(payload: CashflowCostWrite, db: Session = Depends(get_db), current_admin: CurrentAdmin = Depends(require_admin_write)):
    try:
        result = cashflow_service.create_cost(db, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _audit_cost(db, current_admin, "admin.cashflow_cost_created", result)
    return result


@router.put("/cashflow/costs/{cost_id}", response_model=CashflowCostRead)
def update_cost(
    cost_id: uuid.UUID, payload: CashflowCostWrite, db: Session = Depends(get_db), current_admin: CurrentAdmin = Depends(require_admin_write)
):
    try:
        result = cashflow_service.update_cost(db, cost_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Kosten nicht gefunden")
    _audit_cost(db, current_admin, "admin.cashflow_cost_updated", result)
    return result


@router.patch("/cashflow/costs/{cost_id}/status", response_model=CashflowCostRead)
def set_cost_status(
    cost_id: uuid.UUID, payload: CashflowCostStatusUpdate, db: Session = Depends(get_db), current_admin: CurrentAdmin = Depends(require_admin_write)
):
    result = cashflow_service.set_cost_status(db, cost_id, payload.status)
    if result is None:
        raise HTTPException(status_code=404, detail="Kosten nicht gefunden")
    _audit_cost(db, current_admin, "admin.cashflow_cost_status_changed", result)
    return result


@router.delete("/cashflow/costs/{cost_id}", status_code=204)
def delete_cost(cost_id: uuid.UUID, db: Session = Depends(get_db), current_admin: CurrentAdmin = Depends(require_admin_write)):
    if not cashflow_service.delete_cost(db, cost_id):
        raise HTTPException(status_code=404, detail="Kosten nicht gefunden")
    _audit_cost(db, current_admin, "admin.cashflow_cost_deleted", cost_id)
    return Response(status_code=204)
