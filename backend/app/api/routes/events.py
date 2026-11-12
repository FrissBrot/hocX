import json
import uuid

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy import func, select, update

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field

from app.core.db import get_db
from app.core.permissions import P
from app.core.security import CurrentUser, get_current_user, require_permission
from app.schemas.event import EventCreate, EventImportPreview, EventRead, EventUpdate
from app.services import public_id_service
from app.services.event_service import EventService
from app.services.submission_service import SubmissionService
from app.services.audit_service import AuditService
from app.services import photo_event_link_service
from app.services.task_package_service import sync_packages_after_change
from app.models.entities import Event, SubmissionAssignment
from app.core.offload import run_coroutine_in_thread

router = APIRouter()
service = EventService()
submission_service = SubmissionService()
audit = AuditService()


@router.get("/events", response_model=list[EventRead])
def list_events(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_permission(user, P.MEETINGS_READ)
    rows = service.list_events(db, tenant_id=user.current_tenant_id, skip=skip, limit=limit)
    # Teilnehmer-public_ids aller Zeilen mit einer Abfrage vorladen statt bis zu 6 je Termin (N+1).
    EventRead.prime_public_ids(db, rows)
    return rows


@router.post("/events", response_model=EventRead, status_code=status.HTTP_201_CREATED)
def create_event(
    payload: EventCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_permission(user, P.MEETINGS_EDIT)
    try:
        created = service.create_event(db, payload, tenant_id=user.current_tenant_id)
    except (SQLAlchemyError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Event could not be created") from exc
    submission_service.sync_todos_for_event(db, created)
    photo_event_link_service.sync_photos_for_event(db, created)
    sync_packages_after_change(db, tenant_id=user.current_tenant_id, event_tag=created.tag)
    return created


def _parse_column_map(column_map: str) -> dict[str, str] | None:
    if not column_map:
        return None
    try:
        parsed = json.loads(column_map)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="column_map ist kein gültiges JSON") from exc
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
    # Ganze Verarbeitung im Worker-Thread (Concurrency-Audit CONC-001): sie mischt synchrone
    # DB-Zugriffe mit awaits und blockierte sonst den Event-Loop des ganzen Workers.
    return await run_coroutine_in_thread(_preview_events_csv_impl, file=file, column_map=column_map, db=db, user=user)


async def _preview_events_csv_impl(  # loop-ok: nur über run_coroutine_in_thread (core/offload.py)
    file: UploadFile = File(...),
    column_map: str = Form(default=""),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_permission(user, P.MEETINGS_EDIT)
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
    # Ganze Verarbeitung im Worker-Thread (Concurrency-Audit CONC-001): sie mischt synchrone
    # DB-Zugriffe mit awaits und blockierte sonst den Event-Loop des ganzen Workers.
    return await run_coroutine_in_thread(_import_events_csv_impl, file=file, column_map=column_map, db=db, user=user)


async def _import_events_csv_impl(  # loop-ok: nur über run_coroutine_in_thread (core/offload.py)
    file: UploadFile = File(...),
    column_map: str = Form(default=""),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_permission(user, P.MEETINGS_EDIT)
    try:
        content = (await file.read()).decode("utf-8-sig")
        created = service.import_csv(db, content, tenant_id=user.current_tenant_id, column_map=_parse_column_map(column_map))
    except (SQLAlchemyError, UnicodeDecodeError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc) if isinstance(exc, ValueError) else "CSV import failed") from exc
    for event in created:
        photo_event_link_service.sync_photos_for_event(db, event)
    if created:
        submission_service.sync_todos_for_tenant(db, tenant_id=user.current_tenant_id)
    for tag in sorted({event.tag for event in created if event.tag}):
        sync_packages_after_change(db, tenant_id=user.current_tenant_id, event_tag=tag)
    return created


@router.patch("/events/{event_id}", response_model=EventRead)
def patch_event(
    event_id: uuid.UUID,
    payload: EventUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_permission(user, P.MEETINGS_EDIT)
    current = public_id_service.get_by_public_id(db, Event, event_id, tenant_id=user.current_tenant_id)
    if current is None:
        raise HTTPException(status_code=404, detail="Event not found")
    previous_tag = current.tag
    try:
        updated = service.update_event(db, current.id, payload)
    except (SQLAlchemyError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Event could not be updated") from exc
    if updated is None:
        raise HTTPException(status_code=404, detail="Event not found")
    submission_service.sync_todos_for_event(db, updated)
    photo_event_link_service.sync_photos_for_event(db, updated)
    sync_packages_after_change(db, tenant_id=user.current_tenant_id, event_tag=updated.tag)
    if previous_tag and previous_tag != updated.tag:
        # Pakete zum bisherigen Tag verlieren den Termin - sofort nachführen, nicht erst im Tagesjob.
        sync_packages_after_change(db, tenant_id=user.current_tenant_id, event_tag=previous_tag)
    return updated


class EventDeleteImpact(BaseModel):
    submission_count: int
    file_count: int


@router.get("/events/{event_id}/delete-impact", response_model=EventDeleteImpact)
def event_delete_impact(
    event_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Für den Löschdialog: wie viele Abgabe-Einreichungen und Dateien mitgelöscht würden."""
    require_permission(user, P.MEETINGS_EDIT)
    current = public_id_service.get_by_public_id(db, Event, event_id, tenant_id=user.current_tenant_id)
    if current is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return service.delete_impact(db, current.id)


@router.delete("/events/{event_id}", response_model=dict[str, str])
def delete_event(
    event_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_permission(user, P.MEETINGS_EDIT)
    current = public_id_service.get_by_public_id(db, Event, event_id, tenant_id=user.current_tenant_id)
    if current is None:
        raise HTTPException(status_code=404, detail="Event not found")
    deleted_tag = current.tag
    deleted_internal_id = current.id
    try:
        deleted = service.delete_event(db, current.id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Event could not be deleted") from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Event not found")
    # Audit S10, 2026-08-16 - see the identical fix in participants.py.
    audit.log(db, action="event.deleted", actor=user, entity_type="event", entity_id=deleted_internal_id)
    # Offene Abgabe-Pendenzen des gelöschten Termins fallen weg
    submission_service.sync_todos_for_tenant(db, tenant_id=user.current_tenant_id)
    if deleted_tag:
        sync_packages_after_change(db, tenant_id=user.current_tenant_id, event_tag=deleted_tag)
    return {"message": "Event deleted"}


MAX_TAG_LENGTH = 100


class RenameTagPayload(BaseModel):
    old_tag: str = Field(max_length=MAX_TAG_LENGTH * 2)
    new_tag: str = Field(max_length=MAX_TAG_LENGTH * 2)
    # Nur zählen (für die Rückfrage im Frontend), nichts ändern.
    dry_run: bool = False


@router.post("/events/rename-tag", response_model=dict[str, int])
def rename_tag(
    payload: RenameTagPayload,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_permission(user, P.MEETINGS_EDIT)
    tenant_id = user.current_tenant_id
    old_tag = payload.old_tag
    new_tag = payload.new_tag.strip()
    if len(new_tag) > MAX_TAG_LENGTH:
        raise HTTPException(status_code=400, detail="Tag is too long")
    event_count = db.scalar(select(func.count()).select_from(Event).where(Event.tenant_id == tenant_id, Event.tag == old_tag)) or 0
    assignment_count = (
        db.scalar(
            select(func.count())
            .select_from(SubmissionAssignment)
            .where(SubmissionAssignment.tenant_id == tenant_id, SubmissionAssignment.tag_filter == old_tag)
        )
        or 0
    )
    # Zusammenführen: der neue Tag ist bereits an anderen Terminen vergeben.
    target_count = (
        db.scalar(select(func.count()).select_from(Event).where(Event.tenant_id == tenant_id, Event.tag == new_tag))
        if new_tag and new_tag != old_tag
        else 0
    ) or 0
    if payload.dry_run:
        return {
            "updated": 0,
            "events": int(event_count),
            "submission_assignments": int(assignment_count) if new_tag else 0,
            "target_events": int(target_count),
        }
    if new_tag == old_tag:
        return {"updated": 0, "events": int(event_count), "submission_assignments": 0, "target_events": 0}
    result = db.execute(
        update(Event)
        .where(Event.tenant_id == tenant_id, Event.tag == old_tag)
        .values(tag=new_tag or None)
    )
    # Abgaben mit dem alten Tag als Filter ziehen mit, sonst verlieren sie alle Termine. Ein
    # Termin-Abgabe braucht einen Tag (ck_submission_assignment_source): beim Entfernen bleibt
    # der alte Filter stehen und die Abgabe ist leer.
    moved_assignments = 0
    if new_tag:
        moved_assignments = db.execute(
            update(SubmissionAssignment)
            .where(SubmissionAssignment.tenant_id == tenant_id, SubmissionAssignment.tag_filter == old_tag)
            .values(tag_filter=new_tag)
        ).rowcount
    db.commit()
    audit.log(
        db,
        action="event.tag_renamed",
        actor=user,
        entity_type="event_tag",
        details={
            "old_tag": old_tag,
            "new_tag": new_tag or None,
            "events": int(result.rowcount),
            "submission_assignments": int(moved_assignments),
            "merged": bool(target_count),
        },
    )
    submission_service.sync_todos_for_tenant(db, tenant_id=tenant_id)
    for tag in (old_tag, new_tag):
        if tag:
            sync_packages_after_change(db, tenant_id=tenant_id, event_tag=tag)
    return {
        "updated": int(result.rowcount),
        "events": int(result.rowcount),
        "submission_assignments": int(moved_assignments),
        "target_events": int(target_count),
    }
