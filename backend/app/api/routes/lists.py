from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.db import get_db
from app.core.security import CurrentUser, get_current_user, require_admin, require_reader, require_writer
from app.schemas.list_definition import (
    ListDefinitionCreate,
    ListDefinitionRead,
    ListDefinitionUpdate,
    ListEntryCreate,
    ListEntryRead,
    ListEntryUpdate,
)
from app.services.list_service import ListService

router = APIRouter()
service = ListService()


@router.get("/lists", response_model=list[ListDefinitionRead])
def list_definitions(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_reader(user)
    return service.list_definitions(db, tenant_id=user.current_tenant_id)


@router.post("/lists", response_model=ListDefinitionRead, status_code=status.HTTP_201_CREATED)
def create_definition(
    payload: ListDefinitionCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_admin(user)
    try:
        return service.create_definition(db, payload, tenant_id=user.current_tenant_id)
    except (SQLAlchemyError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Liste konnte nicht erstellt werden") from exc


@router.patch("/lists/{list_definition_id}", response_model=ListDefinitionRead)
def patch_definition(
    list_definition_id: int,
    payload: ListDefinitionUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_admin(user)
    current = service.get_definition(db, list_definition_id)
    if current is None or current.tenant_id != user.current_tenant_id:
        raise HTTPException(status_code=404, detail="Liste nicht gefunden")
    try:
        updated = service.update_definition(db, list_definition_id, payload)
    except (SQLAlchemyError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Liste konnte nicht aktualisiert werden") from exc
    if updated is None:
        raise HTTPException(status_code=404, detail="Liste nicht gefunden")
    return updated


@router.delete("/lists/{list_definition_id}", response_model=dict[str, str])
def delete_definition(
    list_definition_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_admin(user)
    current = service.get_definition(db, list_definition_id)
    if current is None or current.tenant_id != user.current_tenant_id:
        raise HTTPException(status_code=404, detail="Liste nicht gefunden")
    try:
        deleted = service.delete_definition(db, list_definition_id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Liste konnte nicht geloescht werden") from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Liste nicht gefunden")
    return {"message": "Liste geloescht"}


@router.get("/lists/{list_definition_id}/entries", response_model=list[ListEntryRead])
def list_entries(
    list_definition_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_reader(user)
    definition = service.get_definition(db, list_definition_id)
    if definition is None or definition.tenant_id != user.current_tenant_id:
        raise HTTPException(status_code=404, detail="Liste nicht gefunden")
    return service.list_entries(db, list_definition_id=list_definition_id)


@router.post("/lists/{list_definition_id}/entries", response_model=ListEntryRead, status_code=status.HTTP_201_CREATED)
def create_entry(
    list_definition_id: int,
    payload: ListEntryCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    definition = service.get_definition(db, list_definition_id)
    if definition is None or definition.tenant_id != user.current_tenant_id:
        raise HTTPException(status_code=404, detail="Liste nicht gefunden")
    try:
        return service.create_entry(db, list_definition_id, payload)
    except (SQLAlchemyError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc) if isinstance(exc, ValueError) else "Eintrag konnte nicht erstellt werden") from exc


@router.patch("/list-entries/{list_entry_id}", response_model=ListEntryRead)
def patch_entry(
    list_entry_id: int,
    payload: ListEntryUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    current = service.get_entry(db, list_entry_id)
    if current is None:
        raise HTTPException(status_code=404, detail="Eintrag nicht gefunden")
    definition = service.get_definition(db, current.list_definition_id)
    if definition is None or definition.tenant_id != user.current_tenant_id:
        raise HTTPException(status_code=404, detail="Eintrag nicht gefunden")
    try:
        updated = service.update_entry(db, list_entry_id, payload)
    except (SQLAlchemyError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc) if isinstance(exc, ValueError) else "Eintrag konnte nicht gespeichert werden") from exc
    if updated is None:
        raise HTTPException(status_code=404, detail="Eintrag nicht gefunden")
    return updated


@router.delete("/list-entries/{list_entry_id}", response_model=dict[str, str])
def delete_entry(
    list_entry_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    current = service.get_entry(db, list_entry_id)
    if current is None:
        raise HTTPException(status_code=404, detail="Eintrag nicht gefunden")
    definition = service.get_definition(db, current.list_definition_id)
    if definition is None or definition.tenant_id != user.current_tenant_id:
        raise HTTPException(status_code=404, detail="Eintrag nicht gefunden")
    try:
        deleted = service.delete_entry(db, list_entry_id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Eintrag konnte nicht geloescht werden") from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Eintrag nicht gefunden")
    return {"message": "Eintrag geloescht"}
