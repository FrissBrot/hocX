from __future__ import annotations

import uuid

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.db import get_db
from app.core.security import CurrentUser, get_current_user, require_all_fines_read, require_finance_write, require_reader
from app.models.entities import AttendanceFine, Protocol
from app.repositories.fines_repository import DuplicateFineError, FinesRepository
from app.schemas.fines import (
    AttendanceFineCreate,
    AttendanceFineListItem,
    AttendanceFineRead,
    CollectFinePayload,
)
from app.services import public_id_service
from app.services.audit_service import AuditService

router = APIRouter()
repo = FinesRepository()
audit = AuditService()


@router.get("/fines", response_model=list[AttendanceFineListItem])
def list_fines(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Readers only see fines assigned to their own participant identity.

    Writer, kassier and admin may inspect all fines in the current tenant; mutation remains
    restricted to kassier and admin below.
    """
    require_reader(user)
    if user.current_role == "reader":
        return repo.list_fines_for_user(db, user.current_tenant_id, user.user_id, skip=skip, limit=limit)
    return repo.list_fines_for_tenant(db, user.current_tenant_id, skip=skip, limit=limit)


def _resolve_protocol_id(db: Session, protocol_id: uuid.UUID, user: CurrentUser) -> int:
    internal_id = public_id_service.resolve_internal_id(db, Protocol, protocol_id, tenant_id=user.current_tenant_id)
    if internal_id is None:
        raise HTTPException(status_code=404, detail="Protocol not found")
    return internal_id


def _resolve_fine_id(db: Session, fine_id: uuid.UUID) -> int:
    # Fine tenant-scoping happens inside the repository methods themselves (they all take
    # tenant_id directly) - this just needs *an* internal id to pass through, same 404 on a
    # bare miss as a real tenant mismatch would eventually produce.
    internal_id = public_id_service.resolve_internal_id(db, AttendanceFine, fine_id)
    if internal_id is None:
        raise HTTPException(status_code=404, detail="Fine not found")
    return internal_id


@router.get("/protocols/{protocol_id}/pending-fines", response_model=list[AttendanceFineListItem])
def list_pending_fines(
    protocol_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_all_fines_read(user)
    internal_id = _resolve_protocol_id(db, protocol_id, user)
    return repo.list_pending_fines_for_protocol(db, internal_id, user.current_tenant_id)


@router.get("/protocols/{protocol_id}/fines", response_model=list[AttendanceFineRead])
def list_protocol_fines(
    protocol_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_all_fines_read(user)
    internal_id = _resolve_protocol_id(db, protocol_id, user)
    return repo.list_fines_for_protocol(db, internal_id, user.current_tenant_id)


@router.post("/fines", response_model=AttendanceFineRead, status_code=status.HTTP_201_CREATED)
def create_fine(
    payload: AttendanceFineCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_finance_write(user)
    try:
        result = repo.create_fine(db, payload, user.current_tenant_id)
    except DuplicateFineError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Fine could not be created") from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Protocol, account or participant not found")
    result_internal_id = public_id_service.resolve_internal_id(db, AttendanceFine, result.id)
    audit.log(
        db, action="fine.created", actor=user, entity_type="attendance_fine", entity_id=result_internal_id,
        details={"protocol_id": str(result.protocol_id), "amount": float(result.amount), "fine_type": result.fine_type},
    )
    return result


@router.delete("/fines/{fine_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_fine(
    fine_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_finance_write(user)
    internal_id = _resolve_fine_id(db, fine_id)
    try:
        deleted = repo.delete_fine(db, internal_id, user.current_tenant_id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Fine could not be deleted") from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Fine not found or already collected")
    audit.log(db, action="fine.deleted", actor=user, entity_type="attendance_fine", entity_id=internal_id)


@router.post("/fines/{fine_id}/collect", response_model=AttendanceFineRead)
def collect_fine(
    fine_id: uuid.UUID,
    payload: CollectFinePayload = CollectFinePayload(),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_finance_write(user)
    internal_id = _resolve_fine_id(db, fine_id)
    collecting_protocol_internal_id = None
    if payload.collecting_protocol_id is not None:
        collecting_protocol_internal_id = public_id_service.resolve_internal_id(
            db, Protocol, payload.collecting_protocol_id, tenant_id=user.current_tenant_id
        )
        if collecting_protocol_internal_id is None:
            raise HTTPException(status_code=404, detail="Protocol not found")
    try:
        result = repo.collect_fine(db, internal_id, user.current_tenant_id, user.user_id, collecting_protocol_internal_id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Fine could not be collected") from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Fine not found or already collected")
    audit.log(db, action="fine.collected", actor=user, entity_type="attendance_fine", entity_id=internal_id)
    return result


@router.post("/fines/{fine_id}/reopen", response_model=AttendanceFineRead)
def reopen_fine(
    fine_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_finance_write(user)
    internal_id = _resolve_fine_id(db, fine_id)
    try:
        result = repo.reopen_fine(db, internal_id, user.current_tenant_id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Fine could not be reopened") from exc
    if result is None:
        raise HTTPException(
            status_code=404,
            detail="Fine not found, not collected, or already finalized in its protocol",
        )
    audit.log(db, action="fine.reopened", actor=user, entity_type="attendance_fine", entity_id=internal_id)
    return result
