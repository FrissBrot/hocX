from __future__ import annotations

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.db import get_db
from app.core.security import CurrentUser, get_current_user, require_finance_access, require_reader
from app.repositories.fines_repository import FinesRepository
from app.schemas.fines import (
    AttendanceFineCreate,
    AttendanceFineListItem,
    AttendanceFineRead,
    CollectFinePayload,
)
from app.services.access_service import AccessService

router = APIRouter()
repo = FinesRepository()
access_service = AccessService()


@router.get("/fines", response_model=list[AttendanceFineListItem])
def list_fines(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Every role sees all fines in the tenant, except restricted readers (participant-linked
    or otherwise scoped accounts) who only see fines from protocols they have access to."""
    require_reader(user)
    if access_service._is_restricted_reader(db, user):
        protocol_ids = access_service.repository.list_protocol_ids(db, user_id=user.user_id, tenant_id=user.current_tenant_id)
        return repo.list_fines_for_protocols(db, user.current_tenant_id, protocol_ids)
    return repo.list_fines_for_tenant(db, user.current_tenant_id)


@router.get("/protocols/{protocol_id}/pending-fines", response_model=list[AttendanceFineListItem])
def list_pending_fines(
    protocol_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_finance_access(user)
    return repo.list_pending_fines_for_protocol(db, protocol_id)


@router.get("/protocols/{protocol_id}/fines", response_model=list[AttendanceFineRead])
def list_protocol_fines(
    protocol_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_finance_access(user)
    return repo.list_fines_for_protocol(db, protocol_id)


@router.post("/fines", response_model=AttendanceFineRead, status_code=status.HTTP_201_CREATED)
def create_fine(
    payload: AttendanceFineCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_finance_access(user)
    try:
        return repo.create_fine(db, payload)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Fine could not be created") from exc


@router.post("/fines/{fine_id}/delete", status_code=status.HTTP_204_NO_CONTENT)
def delete_fine_post(
    fine_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_finance_access(user)
    try:
        deleted = repo.delete_fine(db, fine_id, user.current_tenant_id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Fine could not be deleted") from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Fine not found or already collected")


@router.delete("/fines/{fine_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_fine(
    fine_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_finance_access(user)
    try:
        deleted = repo.delete_fine(db, fine_id, user.current_tenant_id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Fine could not be deleted") from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Fine not found or already collected")


@router.post("/fines/{fine_id}/collect", response_model=AttendanceFineRead)
def collect_fine(
    fine_id: int,
    payload: CollectFinePayload = CollectFinePayload(),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_finance_access(user)
    try:
        result = repo.collect_fine(db, fine_id, user.current_tenant_id, user.user_id, payload.collecting_protocol_id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Fine could not be collected") from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Fine not found or already collected")
    return result


@router.post("/fines/{fine_id}/reopen", response_model=AttendanceFineRead)
def reopen_fine(
    fine_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_finance_access(user)
    try:
        result = repo.reopen_fine(db, fine_id, user.current_tenant_id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Fine could not be reopened") from exc
    if result is None:
        raise HTTPException(
            status_code=404,
            detail="Fine not found, not collected, or already finalized in its protocol",
        )
    return result
