from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.db import get_db
from app.core.security import CurrentUser, get_current_user
from app.schemas.user import UserCreate, UserMergeRequest, UserRead, UserSelfUpdate, UserUpdate
from app.services.user_service import UserService

router = APIRouter()
service = UserService()


@router.get("", response_model=list[UserRead])
def list_users(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    return service.list_users(db, user)


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    try:
        return service.create_user(db, payload, user)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="User could not be created") from exc


@router.get("/me", response_model=UserRead)
def get_me(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    return service.get_self(db, user)


@router.patch("/me", response_model=UserRead)
def patch_me(
    payload: UserSelfUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    try:
        return service.update_self(db, user, payload)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Profile could not be updated") from exc


@router.post("/merge", response_model=UserRead)
def merge_users(
    payload: UserMergeRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    try:
        return service.merge_users(db, source_user_id=payload.source_user_id, target_user_id=payload.target_user_id, actor=user)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Users could not be merged") from exc


@router.get("/{user_id}", response_model=UserRead)
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    current = service.get_user(db, user_id, user)
    if current is None:
        raise HTTPException(status_code=404, detail="User not found")
    return current


@router.patch("/{user_id}", response_model=UserRead)
def patch_user(
    user_id: int,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    try:
        current = service.update_user(db, user_id, payload, user)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="User could not be updated") from exc
    if current is None:
        raise HTTPException(status_code=404, detail="User not found")
    return current


@router.delete("/{user_id}", response_model=dict[str, str])
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    try:
        deleted = service.delete_user(db, user_id, user)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="User could not be deleted") from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="User not found")
    return {"message": "User deleted"}
