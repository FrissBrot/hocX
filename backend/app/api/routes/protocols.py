import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert as pg_insert

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.core.security import CurrentUser, get_current_user, require_reader, require_writer
from app.core.db import get_db, SessionLocal
from app.schemas.protocol import AttendanceExcusePayload, NextSessionRead, ProtocolCreateFromTemplate, ProtocolCycleEventsRead, ProtocolRead, ProtocolTodoRead, ProtocolUpdate, QuickTodoCreate, TodoListItem
from app.services import public_id_service
from app.services.access_service import AccessService
from app.services.audit_service import AuditService
from app.services.event_service import EventService
from app.services.export_service import ExportService
from app.services.protocol_service import ProtocolService
from app.services.protocol_todo_service import ProtocolTodoService
from app.models.entities import Participant, Protocol, ProtocolElement, ProtocolExportCache, StoredFile, UserProtocolScroll, WordImportDocument

router = APIRouter()
service = ProtocolService()
todo_service = ProtocolTodoService()
access_service = AccessService()
audit = AuditService()
event_service = EventService()


def _get_protocol_or_404(db: Session, protocol_id: uuid.UUID, user: CurrentUser) -> Protocol:
    protocol = public_id_service.get_by_public_id(db, Protocol, protocol_id, tenant_id=user.current_tenant_id)
    if protocol is None:
        raise HTTPException(status_code=404, detail="Protocol not found")
    return protocol


async def _generate_pdf_background(protocol_id: int) -> None:
    """Generate a PDF in the background after a protocol is closed."""
    db = SessionLocal()
    try:
        await ExportService().export_pdf(db, protocol_id)
    except Exception:
        pass
    finally:
        db.close()


def _build_protocol_reads(db: Session, protocols: list) -> list[ProtocolRead]:
    """Converts raw Protocol ORM rows to ProtocolRead, bulk-attaching the latest PDF url
    and Word-Import source link. Side-loaded data is looked up by the ORM rows' *internal*
    ids (still available here, before conversion to ProtocolRead's public id) - keep this
    combined instead of splitting into separate pre/post-conversion passes, since anything
    keying off ProtocolRead.id after conversion would only have the public UUID, not the
    internal id these joins need."""
    internal_ids = [p.id for p in protocols]
    if not internal_ids:
        return []

    pdf_rows = db.execute(
        select(ProtocolExportCache.protocol_id, StoredFile.public_id.label("file_public_id"))
        .join(StoredFile, StoredFile.id == ProtocolExportCache.generated_file_id)
        .where(
            ProtocolExportCache.protocol_id.in_(internal_ids),
            ProtocolExportCache.export_format == "pdf",
        )
        .order_by(ProtocolExportCache.id.desc())
    ).all()
    pdf_by_protocol: dict[int, uuid.UUID] = {}
    for row in pdf_rows:
        if row.protocol_id not in pdf_by_protocol:
            pdf_by_protocol[row.protocol_id] = row.file_public_id

    import_rows = db.execute(
        select(
            WordImportDocument.protocol_id,
            WordImportDocument.original_filename,
            StoredFile.public_id.label("stored_file_public_id"),
        )
        .join(StoredFile, StoredFile.id == WordImportDocument.stored_file_id)
        .where(WordImportDocument.protocol_id.in_(internal_ids))
    ).all()
    import_by_protocol = {row.protocol_id: (row.original_filename, row.stored_file_public_id) for row in import_rows}

    result = []
    for p in protocols:
        r = ProtocolRead.model_validate(p)
        if p.id in pdf_by_protocol:
            r.latest_pdf_url = f"/api/stored-files/{pdf_by_protocol[p.id]}/content"
        if p.id in import_by_protocol:
            filename, stored_file_public_id = import_by_protocol[p.id]
            r.import_source_filename = filename
            r.import_source_url = f"/api/stored-files/{stored_file_public_id}/content"
        result.append(r)
    return result


@router.get("/protocols", response_model=list[ProtocolRead])
def list_protocols(
    q: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_reader(user)
    # Unrestricted readers may only see finalized protocols; restricted readers are further
    # scoped below via restrict_to_assigned. Kassier/writer/admin see everything, all statuses.
    if user.current_role == "reader" and not access_service._is_restricted_reader(db, user):
        status_filter = "abgeschlossen"
        q = None
    protocols = service.list_protocols(
        db,
        tenant_id=user.current_tenant_id,
        query=q,
        status=status_filter,
        user_id=user.user_id,
        restrict_to_assigned=access_service._is_restricted_reader(db, user),
        skip=skip,
        limit=limit,
    )
    return _build_protocol_reads(db, protocols)


@router.post("/protocols/from-template", response_model=dict[str, uuid.UUID], status_code=status.HTTP_201_CREATED)
def create_protocol_from_template(
    payload: ProtocolCreateFromTemplate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    try:
        protocol_id = service.create_from_template(db, payload, tenant_id=user.current_tenant_id, created_by=user.user_id)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Protocol could not be created") from exc
    protocol_public_id = public_id_service.resolve_public_id(db, Protocol, protocol_id)
    return {"id": protocol_public_id}


@router.get("/protocols/next-session", response_model=NextSessionRead)
def get_next_session(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_reader(user)
    return service.get_next_session_attendance(db, user.current_tenant_id)


@router.post("/protocols/{protocol_id}/attendance/{participant_id}/excuse", response_model=dict[str, str])
def excuse_participant(
    protocol_id: uuid.UUID,
    participant_id: uuid.UUID,
    payload: AttendanceExcusePayload = AttendanceExcusePayload(),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    protocol = _get_protocol_or_404(db, protocol_id, user)
    participant_internal_id = public_id_service.resolve_internal_id(db, Participant, participant_id, tenant_id=user.current_tenant_id)
    if participant_internal_id is None:
        raise HTTPException(status_code=404, detail="Participant not found")
    # Frozen (abgeschlossen) protocols must never have their attendance/fines touched after
    # the fact - matches the guard every other write path on a protocol's content goes through.
    service.get_protocol_or_404_not_frozen(db, protocol.id)
    try:
        updated = service.set_attendance_excused(db, protocol.id, participant_internal_id, payload.excused)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Attendance status could not be updated") from exc
    if not updated:
        raise HTTPException(status_code=404, detail="No attendance entry found for this participant")
    return {"message": "Participant excused" if payload.excused else "Participant marked unentschuldigt"}


@router.get("/protocols/{protocol_id}", response_model=ProtocolRead)
def get_protocol(protocol_id: uuid.UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_reader(user)
    protocol = _get_protocol_or_404(db, protocol_id, user)
    access_service.ensure_can_read_protocol(db, user, protocol.id)
    return _build_protocol_reads(db, [protocol])[0]


@router.patch("/protocols/{protocol_id}", response_model=ProtocolRead)
def patch_protocol(
    protocol_id: uuid.UUID,
    payload: ProtocolUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    existing = _get_protocol_or_404(db, protocol_id, user)
    protocol_id = existing.id
    if (
        payload.session_notes is not None
        and payload.expected_session_notes is not None
        and payload.expected_session_notes != (existing.session_notes or "")
    ):
        raise HTTPException(
            status_code=409,
            detail="Die Sitzungsnotizen wurden zwischenzeitlich geändert. Der lokale Entwurf bleibt erhalten.",
        )
    try:
        protocol = service.update_protocol(db, protocol_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Protocol could not be updated") from exc
    if protocol is None:
        raise HTTPException(status_code=404, detail="Protocol not found")
    if payload.status is not None and payload.status != existing.status:
        audit.log(db, action="protocol.status_changed", actor=user, entity_type="protocol", entity_id=protocol_id,
                  details={"from": existing.status, "to": payload.status})
        if payload.status == "abgeschlossen":
            background_tasks.add_task(_generate_pdf_background, protocol_id)
    return protocol


_PREVIOUS_STATUS: dict[str, str] = {
    "vorbereitet": "geplant",
    "durchgeführt": "vorbereitet",
    "abgeschlossen": "durchgeführt",
}


@router.post("/protocols/{protocol_id}/revert-status", response_model=ProtocolRead)
def revert_protocol_status(
    protocol_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    existing = _get_protocol_or_404(db, protocol_id, user)
    prev = _PREVIOUS_STATUS.get(existing.status)
    if prev is None:
        raise HTTPException(status_code=400, detail="Protocol is already at the initial status")
    try:
        protocol = service.update_protocol(db, existing.id, ProtocolUpdate(status=prev))
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Status could not be reverted") from exc
    if protocol is None:
        raise HTTPException(status_code=404, detail="Protocol not found")
    audit.log(db, action="protocol.status_reverted", actor=user, entity_type="protocol", entity_id=existing.id,
              details={"from": existing.status, "to": prev})
    return protocol


@router.get("/protocols/{protocol_id}/pending-todos", response_model=list[TodoListItem])
def get_pending_todos(
    protocol_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Open session todos from earlier protocols of the same template."""
    require_reader(user)
    protocol = _get_protocol_or_404(db, protocol_id, user)
    return todo_service.list_pending_for_protocol(
        db,
        protocol_id=protocol.id,
        template_id=protocol.template_id,
        protocol_date=protocol.protocol_date,
    )


@router.get("/protocols/{protocol_id}/cycle-events", response_model=ProtocolCycleEventsRead)
def get_cycle_events(
    protocol_id: uuid.UUID,
    scope: str = Query("current", pattern="^(current|all)$"),
    search: str = Query(""),
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=500),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Termin-Pool für die Planungsmodus-Popups (Terminübersicht, Checkbox-Auswahl).

    scope=current: nur Termine des aktuellen Zyklus des Protokolls (Template-CycleConfig
    + protocol_date). Fällt auf alle Termine zurück (cycle=null), wenn kein Zyklus
    konfiguriert ist. scope=all: alle Termine des Mandanten, unabhängig vom Zyklus.
    """
    require_reader(user)
    protocol = _get_protocol_or_404(db, protocol_id, user)
    items, total, cycle = event_service.list_for_protocol_cycle(
        db, protocol=protocol, scope=scope, search=search, skip=skip, limit=limit
    )
    return ProtocolCycleEventsRead(items=items, total=total, cycle=cycle)


@router.post("/protocols/{protocol_id}/quick-todos", response_model=dict, status_code=status.HTTP_201_CREATED)
def create_quick_todo(
    protocol_id: uuid.UUID,
    payload: QuickTodoCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Create a session todo, auto-creating the Sitzungsnotizen element+block if needed."""
    require_writer(user)
    existing = _get_protocol_or_404(db, protocol_id, user)
    # Same freeze guard as todos.py's create_todo/patch_todo/delete_todo - a frozen
    # (abgeschlossen) protocol must not gain new blocks/todos after the fact.
    service.get_protocol_or_404_not_frozen(db, existing.id)
    try:
        block, todo = service.create_quick_todo(
            db,
            protocol_id=existing.id,
            task=payload.task,
            tag=payload.tag,
            created_by=user.user_id,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Todo could not be created") from exc
    return {
        "block_id": block.public_id,
        "todo_id": todo.public_id,
        "element_id": public_id_service.resolve_public_id(db, ProtocolElement, block.protocol_element_id),
    }


@router.delete("/protocols/{protocol_id}", response_model=dict[str, str])
def delete_protocol(
    protocol_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    existing = _get_protocol_or_404(db, protocol_id, user)
    audit_details = {"protocol_number": existing.protocol_number, "title": existing.title, "status": existing.status}
    try:
        deleted = service.delete_protocol(db, existing.id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Protocol could not be deleted") from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Protocol not found")
    audit.log(db, action="protocol.deleted", actor=user, entity_type="protocol", entity_id=existing.id,
              details=audit_details)
    return {"message": "Protocol deleted"}


class ElementPositionPayload(BaseModel):
    element_id: uuid.UUID


@router.get("/protocols/{protocol_id}/scroll-position")
def get_element_position(
    protocol_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_reader(user)
    # Audit S11, 2026-08-16: only require_reader (any tenant) was checked before, no
    # protocol-tenant scoping - the (user_id, protocol_id) key limits blast radius (can only
    # ever affect this user's own remembered scroll position), but a fremde protocol_id
    # should still 404 rather than silently succeed.
    protocol = _get_protocol_or_404(db, protocol_id, user)
    row = db.get(UserProtocolScroll, (user.user_id, protocol.id))
    if row is None:
        return {"element_id": None}
    return {"element_id": public_id_service.resolve_public_id(db, ProtocolElement, row.last_element_id)}


@router.put("/protocols/{protocol_id}/scroll-position", status_code=status.HTTP_204_NO_CONTENT)
def save_element_position(
    protocol_id: uuid.UUID,
    payload: ElementPositionPayload,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_reader(user)
    # Audit S11, 2026-08-16 - see get_element_position's identical check above.
    protocol = _get_protocol_or_404(db, protocol_id, user)
    element_internal_id = public_id_service.resolve_internal_id(db, ProtocolElement, payload.element_id)
    if element_internal_id is None:
        raise HTTPException(status_code=404, detail="Element not found")
    stmt = (
        pg_insert(UserProtocolScroll)
        .values(user_id=user.user_id, protocol_id=protocol.id, last_element_id=element_internal_id)
        .on_conflict_do_update(
            index_elements=["user_id", "protocol_id"],
            set_={"last_element_id": element_internal_id, "updated_at": func.now()},
        )
    )
    db.execute(stmt)
    db.commit()
