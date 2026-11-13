import uuid
from types import SimpleNamespace

from sqlalchemy import case, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.db import get_db
from app.core.permissions import P
from app.core.security import CurrentUser, get_current_user, require_permission
from app.models.entities import ElementType, Event, Protocol, ProtocolElement, ProtocolElementBlock, ProtocolTodo, Template
from app.schemas.protocol import (
    ProtocolTodoCreate,
    ProtocolTodoRead,
    ProtocolTodoUpdate,
    TodoDetails,
    TodoDetailsUpdate,
    TodoListItem,
)
from app.services import public_id_service
from app.services.access_service import AccessService
from app.services.audit_service import AuditService
from app.services.protocol_service import ProtocolService
from app.services.protocol_todo_service import ProtocolTodoService
from app.services import todo_fine_service

router = APIRouter()
service = ProtocolTodoService()
access_service = AccessService()
audit = AuditService()
protocol_service = ProtocolService()


def _todo_or_404(db: Session, user: CurrentUser, todo_id: uuid.UUID) -> ProtocolTodo:
    """Todo des eigenen Mandanten mit Leserecht. Fremde und unbekannte IDs ergeben 404 (kein
    Existenz-Orakel über Mandanten hinweg, SECURITY-RULES 1.1/1.6)."""
    if user.current_tenant_id is None:
        raise HTTPException(status_code=404, detail="Todo not found")
    todo = public_id_service.get_by_public_id(db, ProtocolTodo, todo_id, tenant_id=user.current_tenant_id)
    if todo is None:
        raise HTTPException(status_code=404, detail="Todo not found")
    access_service.ensure_can_read_todo(db, user, todo.id)
    return todo


def _get_protocol_or_404(db: Session, protocol_id: int):
    """Todos leben über ihr Protokoll hinaus: auch nach "abgeschlossen" dürfen sie angelegt,
    bearbeitet, erledigt und gelöscht werden. Deshalb hier bewusst nicht
    get_protocol_or_404_not_frozen - das abgeschlossene Protokoll selbst zeigt die beim
    Abschluss eingefrorene Momentaufnahme (protocol.todos_snapshot_json)."""
    protocol = protocol_service.get_protocol(db, protocol_id)
    if protocol is None:
        raise HTTPException(status_code=404, detail="Protocol not found")
    return protocol


@router.post("/todos", response_model=TodoListItem, status_code=status.HTTP_201_CREATED)
def create_standalone_todo(
    payload: ProtocolTodoCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Create a todo not tied to any protocol block."""
    require_permission(user, P.MEETINGS_EDIT)
    try:
        todo = service.create_standalone_todo(db, user.current_tenant_id, payload, actor_user_id=user.user_id)
    except (SQLAlchemyError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Todo could not be created") from exc
    row = service.repository.get_row(db, todo.id)
    if row is None:
        raise HTTPException(status_code=500, detail="Created todo not found")
    return service._row_to_list_item(db, row)


@router.get("/todos/blocks")
def list_todo_blocks(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Aufgabenblöcke der Protokolle, die der Benutzer lesen darf (dieselbe Regel wie die
    Protokollliste - vorher sahen eingeschränkte Leser hier Titel aller Protokolle, S-3)."""
    require_permission(user, P.MEETINGS_READ)
    return service.list_todo_blocks(db, user.current_tenant_id, visible=access_service.protocol_visibility(db, user))


@router.get("/todos", response_model=list[TodoListItem])
def list_all_todos(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Every role sees all tenant todos, except restricted readers (participant-linked or
    otherwise scoped accounts) who only see todos from protocols they have access to, plus
    anything directly assigned to them."""
    require_permission(user, P.MEETINGS_READ)
    if access_service._is_restricted_reader(db, user):
        protocol_ids = access_service.repository.list_protocol_ids(db, user_id=user.user_id, tenant_id=user.current_tenant_id)
        return service.list_todos_for_protocols_or_assigned(db, user.current_tenant_id, protocol_ids, user.user_id, skip=skip, limit=limit)
    return service.list_todos_for_tenant(db, user.current_tenant_id, skip=skip, limit=limit)


@router.get("/todos/my", response_model=list[TodoListItem])
def list_my_todos(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Always returns only todos assigned to the current user."""
    require_permission(user, P.MEETINGS_READ)
    return service.list_todos_for_user(db, user.current_tenant_id, user.user_id, skip=skip, limit=limit)


@router.get("/protocol-element-blocks/{protocol_element_block_id}/todos", response_model=list[ProtocolTodoRead])
def list_todos(
    protocol_element_block_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_permission(user, P.MEETINGS_READ)
    block = public_id_service.get_by_public_id(db, ProtocolElementBlock, protocol_element_block_id, tenant_id=user.current_tenant_id)
    if block is None:
        raise HTTPException(status_code=404, detail="Protocol element block not found")
    # Gleiche Prüfung wie ensure_can_read_protocol_block, aber das Protokoll nur einmal ermitteln
    protocol_id = access_service.repository.protocol_id_for_block(db, protocol_element_block_id=block.id)
    if protocol_id is None:
        raise HTTPException(status_code=404, detail="Protocol block not found")
    access_service.ensure_can_read_protocol(db, user, protocol_id)
    snapshot = _frozen_todo_snapshot(db, protocol_id)
    if snapshot is not None:
        return service.snapshot_todos_for_block(snapshot, block.id)
    return service.list_todos(db, block.id)


def _frozen_todo_snapshot(db: Session, protocol_id: int) -> dict | None:
    """Eingefrorene Aufgaben eines abgeschlossenen Protokolls (frozen_snapshot), ohne die ganze
    Protokollzeile zu laden: das Snapshot-JSON nur, wenn das Protokoll abgeschlossen ist."""
    row = db.execute(
        select(
            Protocol.status,
            case((Protocol.status == "abgeschlossen", Protocol.todos_snapshot_json), else_=None).label("todos_snapshot_json"),
        ).where(Protocol.id == protocol_id)
    ).one_or_none()
    if row is None:
        return None
    return service.frozen_snapshot(SimpleNamespace(status=row.status, todos_snapshot_json=row.todos_snapshot_json))


@router.get("/protocols/{protocol_id}/block-todos", response_model=dict[uuid.UUID, list[ProtocolTodoRead]])
def list_protocol_block_todos(
    protocol_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Aufgaben aller Aufgabenblöcke eines Protokolls in einer Anfrage (Block-public_id ->
    Liste wie GET /protocol-element-blocks/{id}/todos). Die Protokollseite holte sie vorher
    mit einer Anfrage je Block. Gleiche Prüfungen wie die Einzelroute: meetings.read und
    Leserecht am Protokoll (Mandant, Status, Teilnehmer-Zuordnung); fremde oder unbekannte
    Protokolle ergeben 404."""
    require_permission(user, P.MEETINGS_READ)
    protocol = public_id_service.get_by_public_id(db, Protocol, protocol_id, tenant_id=user.current_tenant_id)
    if protocol is None:
        raise HTTPException(status_code=404, detail="Protocol not found")
    access_service.ensure_can_read_protocol(db, user, protocol.id)
    blocks = db.execute(
        select(ProtocolElementBlock.id, ProtocolElementBlock.public_id)
        .join(ProtocolElement, ProtocolElement.id == ProtocolElementBlock.protocol_element_id)
        .join(ElementType, ElementType.id == ProtocolElementBlock.element_type_id)
        .where(ProtocolElement.protocol_id == protocol.id, ElementType.code == "todo")
        .order_by(ProtocolElement.sort_index.asc(), ProtocolElementBlock.sort_index.asc(), ProtocolElementBlock.id.asc())
    ).all()
    result: dict[uuid.UUID, list[ProtocolTodoRead]] = {}
    snapshot = service.frozen_snapshot(protocol)
    if snapshot is not None:
        for block_id, block_public_id in blocks:
            result[block_public_id] = service.snapshot_todos_for_block(snapshot, block_id)
        return result
    query, *_ = service.repository._base_todo_query()
    rows = db.execute(
        query.where(ProtocolTodo.protocol_element_block_id.in_([block_id for block_id, _ in blocks])).order_by(
            ProtocolTodo.protocol_element_block_id.asc(), ProtocolTodo.sort_index.asc(), ProtocolTodo.id.asc()
        )
    ).all() if blocks else []
    service._prime_public_ids(db, rows)
    rows_by_block: dict[int, list] = {}
    for row in rows:
        rows_by_block.setdefault(row.ProtocolTodo.protocol_element_block_id, []).append(row)
    for block_id, block_public_id in blocks:
        result[block_public_id] = [service._row_to_todo_read(db, row) for row in rows_by_block.get(block_id, [])]
    return result


@router.post(
    "/protocol-element-blocks/{protocol_element_block_id}/todos",
    response_model=ProtocolTodoRead,
    status_code=status.HTTP_201_CREATED,
)
def create_todo(
    protocol_element_block_id: uuid.UUID,
    payload: ProtocolTodoCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_permission(user, P.MEETINGS_EDIT)
    block = public_id_service.get_by_public_id(db, ProtocolElementBlock, protocol_element_block_id, tenant_id=user.current_tenant_id)
    if block is None:
        raise HTTPException(status_code=404, detail="Protocol element block not found")
    access_service.ensure_can_read_protocol_block(db, user, block.id)
    protocol_id = access_service.repository.protocol_id_for_block(db, protocol_element_block_id=block.id)
    protocol = _get_protocol_or_404(db, protocol_id)
    track_changes_active = bool(protocol.status == "geplant" and protocol.track_changes_enabled)
    try:
        todo = service.create_todo(db, block.id, payload, track_changes_active=track_changes_active, actor_user_id=user.user_id)
    except (SQLAlchemyError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Todo could not be created") from exc
    todos = service.list_todos(db, block.id)
    return next(item for item in todos if item.id == todo.public_id)


@router.get("/protocol-todos/{todo_id}/due-events")
def get_todo_due_events(
    todo_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Return upcoming events for due-date selection, filtered by the template's todo_due_event_tag."""
    require_permission(user, P.MEETINGS_READ)
    todo = _todo_or_404(db, user, todo_id)
    today = todo_fine_service.today()

    tag_filter: str | None = None
    next_event_public_id: uuid.UUID | None = None

    if todo.protocol_element_block_id:
        row = db.execute(
            select(Template.todo_due_event_tag, Template.next_event_id)
            .join(Protocol, Protocol.template_id == Template.id)
            .join(ProtocolElement, ProtocolElement.protocol_id == Protocol.id)
            .join(ProtocolElementBlock, ProtocolElementBlock.protocol_element_id == ProtocolElement.id)
            .where(ProtocolElementBlock.id == todo.protocol_element_block_id)
        ).first()
        if row:
            tag_filter = row.todo_due_event_tag
            if row.next_event_id is not None:
                next_event_public_id = public_id_service.resolve_public_id(db, Event, row.next_event_id)

    stmt = select(Event).where(
        Event.tenant_id == user.current_tenant_id,
        Event.event_date >= today,
    )
    if tag_filter:
        tag_lower = tag_filter.strip().lower()
        stmt = stmt.where(Event.tag.ilike(f"%{tag_lower}%"))
    stmt = stmt.order_by(Event.event_date.asc()).limit(50)
    events = db.execute(stmt).scalars().all()

    return {
        "next_event_id": next_event_public_id,
        "tag_filter": tag_filter,
        "events": [
            {
                "id": e.public_id,
                "title": e.title,
                "event_date": e.event_date.isoformat(),
                "event_end_date": e.event_end_date.isoformat() if e.event_end_date else None,
                "tag": e.tag,
            }
            for e in events
        ],
    }



# Validierungsfehler aus ProtocolTodoService.update_todo → stabiler Code und lesbare Meldung
_TODO_VALUE_ERRORS = {
    "Assigned participant is not available for this template": (
        "todo_assignee_unavailable",
        "Die verantwortliche Person ist für dieses Protokoll nicht mehr verfügbar (z. B. aus der Vorlage entfernt oder inaktiv). Bitte eine andere Person wählen.",
    ),
    "Assigned participants must be a list": ("todo_invalid", "Die Pendenz konnte nicht gespeichert werden: ungültige Angabe."),
    "Due event is not available for this tenant": ("todo_due_event_unavailable", "Der gewählte Fälligkeitstermin ist nicht mehr verfügbar."),
    "Assigned user is not available for this tenant": ("todo_assignee_unavailable", "Die verantwortliche Person ist nicht mehr verfügbar. Bitte eine andere Person wählen."),
    "Unknown todo status": ("todo_invalid", "Unbekannter Status."),
}

@router.patch("/protocol-todos/{todo_id}", response_model=ProtocolTodoRead)
def patch_todo(
    todo_id: uuid.UUID,
    payload: ProtocolTodoUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    # Deliberately not gated by the collaboration Redis lock the way
    # protocol_elements.py's block PATCH/text PUT now are: unlike protocol element blocks,
    # individual todos have no corresponding field_key in the collaboration lock domain
    # today (session-todos-section.tsx/todo-list-view.tsx never call lockField for a todo
    # edit - only the focused-element-editor's per-block/per-cell text and config fields
    # do). Adding a check here would either be a permanent no-op (no lock is ever held
    # under a "todo-<id>" key) or would have to piggyback on the parent block's lock, which
    # would reject normal todo edits any time someone else merely has that block's text
    # field focused - a worse false-positive than the gap it would close. Two people
    # editing the same todo concurrently therefore remains last-write-wins, same as before
    # this pass; a real fix would need the frontend to start locking todos as its own
    # field_key first.
    require_permission(user, P.MEETINGS_EDIT)
    existing = _todo_or_404(db, user, todo_id)
    previous_status_id = existing.todo_status_id
    protocol_id = access_service.repository.protocol_id_for_todo(db, todo_id=existing.id)
    # Standalone todos (protocol_id None) have no protocol at all.
    protocol = _get_protocol_or_404(db, protocol_id) if protocol_id else None
    track_changes_active = bool(protocol and protocol.status == "geplant" and protocol.track_changes_enabled)
    fine_changes: dict = {}
    try:
        todo = service.update_todo(
            db, existing.id, payload, track_changes_active=track_changes_active, actor_user_id=user.user_id,
            can_manage_fines=user.can(P.FINANCES_MANAGE), fine_changes=fine_changes,
        )
    except todo_fine_service.TodoFineError as exc:
        # Die Prüfung läuft vor jedem Schreiben - nichts zurückzurollen
        raise HTTPException(status_code=409, detail={"code": exc.code, "message": str(exc)}) from exc
    except ValueError as exc:
        # Erwartete Validierung (nicht ins Fehlerprotokoll): Grund mit stabilem Code zurückgeben,
        # statt ihn hinter «Todo could not be updated» zu verstecken
        db.rollback()
        code, message = _TODO_VALUE_ERRORS.get(str(exc), ("todo_invalid", "Die Pendenz konnte nicht gespeichert werden: ungültige Angabe."))
        raise HTTPException(status_code=400, detail={"code": code, "message": message}) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Todo could not be updated") from exc
    if todo is None:
        raise HTTPException(status_code=404, detail="Todo not found")
    if payload.todo_status_id is not None and payload.todo_status_id != previous_status_id:
        audit.log(
            db, action="todo.status_changed", actor=user, entity_type="protocol_todo", entity_id=existing.id,
            details={"from_status_id": previous_status_id, "to_status_id": payload.todo_status_id},
        )
    if fine_changes:
        # Fälligkeit, Verantwortliche, Tags oder Abbrechen: kann eine laufende Busse ändern
        audit.log(db, action="todo.fine_relevant_changed", actor=user, entity_type="protocol_todo", entity_id=existing.id, details=fine_changes)
    if todo.protocol_element_block_id is None:
        # Standalone (z. B. aus einem Aufgabenpaket): nur diese eine Zeile laden statt aller
        # protokollfreien Todos.
        row = service.repository.get_row(db, todo.id)
        if row is None:
            raise HTTPException(status_code=404, detail="Todo not found")
        return service._row_to_todo_read(db, row)
    todos = service.list_todos(db, todo.protocol_element_block_id)
    return next(item for item in todos if item.id == todo_id)


@router.get("/protocol-todos/{todo_id}/details", response_model=TodoDetails)
def get_todo_details(
    todo_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Notizen und verknüpfte Dateien für das Todo-Popup (nicht in Liste/Übersicht/Export)."""
    require_permission(user, P.MEETINGS_READ)
    return service.get_details(db, _todo_or_404(db, user, todo_id))


@router.put("/protocol-todos/{todo_id}/details", response_model=TodoDetails)
def put_todo_details(
    todo_id: uuid.UUID,
    payload: TodoDetailsUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_permission(user, P.MEETINGS_EDIT)
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    todo = _todo_or_404(db, user, todo_id)
    try:
        return service.update_details(db, todo, payload, tenant_id=user.current_tenant_id)
    except (SQLAlchemyError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Todo details could not be saved") from exc


@router.post("/protocol-todos/{todo_id}/accept-tracked-change")
def accept_todo_tracked_change(
    todo_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """'Ausblenden' for one todo's red tracked-change highlight - keeps the todo, just
    stops marking it as changed/added/pending-delete."""
    require_permission(user, P.MEETINGS_EDIT)
    existing = _todo_or_404(db, user, todo_id)
    protocol_id = access_service.repository.protocol_id_for_todo(db, todo_id=existing.id)
    # Standalone todos (protocol_id None) have no tracked-change concept in practice, but
    # guard consistently with patch/delete above rather than special-casing this endpoint.
    if protocol_id:
        protocol_service.get_protocol_or_404_not_frozen(db, protocol_id)
    try:
        result = service.accept_tracked_change(db, existing.id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Change could not be accepted") from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Todo not found")
    hard_deleted, block_id = result
    if hard_deleted or block_id is None:
        return {"todo": None}
    todos = service.list_todos(db, block_id)
    todo_read = next((item for item in todos if item.id == todo_id), None)
    return {"todo": todo_read}


@router.delete("/protocol-todos/{todo_id}")
def delete_todo(
    todo_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_permission(user, P.MEETINGS_EDIT)
    existing = _todo_or_404(db, user, todo_id)
    protocol_id = access_service.repository.protocol_id_for_todo(db, todo_id=existing.id)
    # Standalone todos (protocol_id None) have no protocol at all.
    protocol = _get_protocol_or_404(db, protocol_id) if protocol_id else None
    track_changes_active = bool(protocol and protocol.status == "geplant" and protocol.track_changes_enabled)
    # Löschen beendet eine laufende Busse: nicht durch die gebüsste Person selbst. Eingefrorene
    # Bussen bleiben stehen (todo_fine.protocol_todo_id ON DELETE SET NULL, Snapshots).
    try:
        todo_fine_service.ensure_may_change(db, existing, actor_user_id=user.user_id, can_manage=user.can(P.FINANCES_MANAGE))
    except todo_fine_service.TodoFineError as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code, "message": str(exc)}) from exc
    running_before = todo_fine_service.running_amount(db, existing)
    try:
        result = service.delete_todo(db, existing.id, track_changes_active=track_changes_active)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Todo could not be deleted") from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Todo not found")
    hard_deleted, block_id = result
    audit.log(
        db, action="todo.deleted", actor=user, entity_type="protocol_todo", entity_id=existing.id,
        details={"running_fine_before": str(running_before)} if running_before else None,
    )
    if hard_deleted or block_id is None:
        return {"pending_delete": False, "message": "Todo deleted", "todo": None}
    todos = service.list_todos(db, block_id)
    todo_read = next((item for item in todos if item.id == todo_id), None)
    return {"pending_delete": True, "message": "Todo pending delete", "todo": todo_read}
