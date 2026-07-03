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
    DeleteFinePayload,
    SetDeleteCommentPayload,
)

router = APIRouter()
repo = FinesRepository()


@router.get("/fines", response_model=list[AttendanceFineListItem])
def list_fines(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Finance roles (kassier/writer/admin) see all fines; reader sees only their own."""
    require_reader(user)
    has_finance = user.is_superadmin or user.current_role in {"kassier", "writer", "admin"}
    if has_finance:
        return repo.list_fines_for_tenant(db, user.current_tenant_id)
    participant_id = repo.get_participant_id_for_user(db, user.current_tenant_id, user.user_id)
    if participant_id is None:
        return []
    return repo.list_fines_for_participant(db, user.current_tenant_id, participant_id)


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


@router.post("/fines/{fine_id}/delete", response_model=AttendanceFineRead)
def delete_fine(
    fine_id: int,
    payload: DeleteFinePayload = DeleteFinePayload(),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_finance_access(user)
    try:
        result = repo.delete_fine(db, fine_id, user.current_tenant_id, payload.delete_comment, payload.closing_protocol_id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Fine could not be deleted") from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Fine not found or already collected")
    return result


@router.patch("/fines/{fine_id}/delete-comment", response_model=AttendanceFineRead)
def set_delete_comment(
    fine_id: int,
    payload: SetDeleteCommentPayload,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_finance_access(user)
    result = repo.set_delete_comment(db, fine_id, user.current_tenant_id, payload.delete_comment)
    if result is None:
        raise HTTPException(status_code=404, detail="Fine not found or not in deleted state")
    return result


@router.post("/fines/{fine_id}/collect", response_model=AttendanceFineRead)
def collect_fine(
    fine_id: int,
    payload: CollectFinePayload = CollectFinePayload(),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_finance_access(user)
    try:
        result = repo.collect_fine(db, fine_id, user.current_tenant_id, payload.collecting_protocol_id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Fine could not be collected") from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Fine not found or already collected")
    return result
