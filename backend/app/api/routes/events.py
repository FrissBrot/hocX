import json

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy import update

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel

from app.core.db import get_db
from app.core.security import CurrentUser, get_current_user, require_reader, require_writer
from app.schemas.event import EventCreate, EventImportPreview, EventRead, EventUpdate
from app.services.event_service import EventService
from app.services.submission_service import SubmissionService
from app.models.entities import Event

router = APIRouter()
service = EventService()
submission_service = SubmissionService()


@router.get("/events", response_model=list[EventRead])
def list_events(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_reader(user)
    return service.list_events(db, tenant_id=user.current_tenant_id, skip=skip, limit=limit)


@router.post("/events", response_model=EventRead, status_code=status.HTTP_201_CREATED)
def create_event(
    payload: EventCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    try:
        created = service.create_event(db, payload, tenant_id=user.current_tenant_id)
    except (SQLAlchemyError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Event could not be created") from exc
    submission_service.sync_todos_for_event(db, created)
    return created


def _parse_column_map(column_map: str) -> dict[str, str] | None:
    if not column_map:
        return None
    try:
        parsed = json.loads(column_map)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="column_map ist kein gueltiges JSON") from exc
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=400, detail="column_map muss ein Objekt sein")
    return {str(key): str(value) for key, value in parsed.items()}


@router.post("/events/import-csv/preview", response_model=EventImportPreview)
async def preview_events_csv(
    file: UploadFile = File(...),
    column_map: str = Form(default=""),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    try:
        content = (await file.read()).decode("utf-8-sig")
        return service.preview_csv(db, content, column_map=_parse_column_map(column_map))
    except (UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc) if isinstance(exc, ValueError) else "CSV preview failed") from exc


@router.post("/events/import-csv", response_model=list[EventRead], status_code=status.HTTP_201_CREATED)
async def import_events_csv(
    file: UploadFile = File(...),
    column_map: str = Form(default=""),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    try:
        content = (await file.read()).decode("utf-8-sig")
        return service.import_csv(db, content, tenant_id=user.current_tenant_id, column_map=_parse_column_map(column_map))
    except (SQLAlchemyError, UnicodeDecodeError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc) if isinstance(exc, ValueError) else "CSV import failed") from exc


@router.patch("/events/{event_id}", response_model=EventRead)
def patch_event(
    event_id: int,
    payload: EventUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    current = service.get_event(db, event_id)
    if current is None or current.tenant_id != user.current_tenant_id:
        raise HTTPException(status_code=404, detail="Event not found")
    try:
        updated = service.update_event(db, event_id, payload)
    except (SQLAlchemyError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Event could not be updated") from exc
    if updated is None:
        raise HTTPException(status_code=404, detail="Event not found")
    submission_service.sync_todos_for_event(db, updated)
    return updated


@router.delete("/events/{event_id}", response_model=dict[str, str])
def delete_event(
    event_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    current = service.get_event(db, event_id)
    if current is None or current.tenant_id != user.current_tenant_id:
        raise HTTPException(status_code=404, detail="Event not found")
    try:
        deleted = service.delete_event(db, event_id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Event could not be deleted") from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Event not found")
    return {"message": "Event deleted"}


class RenameTagPayload(BaseModel):
    old_tag: str
    new_tag: str


@router.post("/events/rename-tag", response_model=dict[str, int])
def rename_tag(
    payload: RenameTagPayload,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    result = db.execute(
        update(Event)
        .where(Event.tenant_id == user.current_tenant_id, Event.tag == payload.old_tag)
        .values(tag=payload.new_tag or None)
    )
    db.commit()
    return {"updated": result.rowcount}
