from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.db import get_db
from app.core.security import CurrentUser, get_current_user, require_reader, require_writer
from app.models.entities import Event, Protocol, ProtocolElement, ProtocolElementBlock, ProtocolTodo, Template
from app.schemas.protocol import ProtocolTodoCreate, ProtocolTodoRead, ProtocolTodoUpdate, TodoListItem
from app.services.access_service import AccessService
from app.services.audit_service import AuditService
from app.services.protocol_service import ProtocolService
from app.services.protocol_todo_service import ProtocolTodoService

router = APIRouter()
service = ProtocolTodoService()
access_service = AccessService()
audit = AuditService()
protocol_service = ProtocolService()


@router.post("/todos", response_model=TodoListItem, status_code=status.HTTP_201_CREATED)
def create_standalone_todo(
    payload: ProtocolTodoCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Create a todo not tied to any protocol block."""
    require_writer(user)
    try:
        todo = service.create_standalone_todo(db, user.current_tenant_id, payload)
    except (SQLAlchemyError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Todo could not be created") from exc
    rows = service.repository.list_for_tenant(db, user.current_tenant_id)
    row = next((r for r in rows if r.ProtocolTodo.id == todo.id), None)
    if row is None:
        raise HTTPException(status_code=500, detail="Created todo not found")
    return service._row_to_list_item(row)


@router.get("/todos/blocks")
def list_todo_blocks(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Return all protocol todo blocks available to the tenant."""
    require_reader(user)
    return service.list_todo_blocks(db, user.current_tenant_id)


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
    require_reader(user)
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
    require_reader(user)
    return service.list_todos_for_user(db, user.current_tenant_id, user.user_id, skip=skip, limit=limit)


@router.get("/protocol-element-blocks/{protocol_element_block_id}/todos", response_model=list[ProtocolTodoRead])
def list_todos(
    protocol_element_block_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_reader(user)
    access_service.ensure_can_read_protocol_block(db, user, protocol_element_block_id)
    return service.list_todos(db, protocol_element_block_id)


@router.post(
    "/protocol-element-blocks/{protocol_element_block_id}/todos",
    response_model=ProtocolTodoRead,
    status_code=status.HTTP_201_CREATED,
)
def create_todo(
    protocol_element_block_id: int,
    payload: ProtocolTodoCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    access_service.ensure_can_read_protocol_block(db, user, protocol_element_block_id)
    protocol_id = access_service.repository.protocol_id_for_block(db, protocol_element_block_id=protocol_element_block_id)
    protocol = protocol_service.get_protocol_or_404_not_frozen(db, protocol_id)
    track_changes_active = bool(protocol.status == "geplant" and protocol.track_changes_enabled)
    try:
        todo = service.create_todo(db, protocol_element_block_id, payload, track_changes_active=track_changes_active)
    except (SQLAlchemyError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Todo could not be created") from exc
    todos = service.list_todos(db, protocol_element_block_id)
    return next(item for item in todos if item.id == todo.id)


@router.get("/protocol-todos/{todo_id}/due-events")
def get_todo_due_events(
    todo_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Return upcoming events for due-date selection, filtered by the template's todo_due_event_tag."""
    require_reader(user)
    access_service.ensure_can_read_todo(db, user, todo_id)
    today = date.today()

    todo = db.get(ProtocolTodo, todo_id)
    if todo is None:
        raise HTTPException(status_code=404, detail="Todo not found")

    tag_filter: str | None = None
    next_event_id: int | None = None

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
            next_event_id = row.next_event_id

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
        "next_event_id": next_event_id,
        "tag_filter": tag_filter,
        "events": [
            {
                "id": e.id,
                "title": e.title,
                "event_date": e.event_date.isoformat(),
                "event_end_date": e.event_end_date.isoformat() if e.event_end_date else None,
                "tag": e.tag,
            }
            for e in events
        ],
    }


@router.patch("/protocol-todos/{todo_id}", response_model=ProtocolTodoRead)
def patch_todo(
    todo_id: int,
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
    require_writer(user)
    access_service.ensure_can_read_todo(db, user, todo_id)
    existing = service.repository.get(db, todo_id)
    previous_status_id = existing.todo_status_id if existing else None
    protocol_id = access_service.repository.protocol_id_for_todo(db, todo_id=todo_id)
    # Standalone todos (protocol_id None, not tied to any block) have no "abgeschlossen"
    # concept and stay editable; block-linked todos are rejected once their protocol froze.
    protocol = protocol_service.get_protocol_or_404_not_frozen(db, protocol_id) if protocol_id else None
    track_changes_active = bool(protocol and protocol.status == "geplant" and protocol.track_changes_enabled)
    try:
        todo = service.update_todo(db, todo_id, payload, track_changes_active=track_changes_active)
    except (SQLAlchemyError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Todo could not be updated") from exc
    if todo is None:
        raise HTTPException(status_code=404, detail="Todo not found")
    if payload.todo_status_id is not None and payload.todo_status_id != previous_status_id:
        audit.log(
            db, action="todo.status_changed", actor=user, entity_type="protocol_todo", entity_id=todo_id,
            details={"from_status_id": previous_status_id, "to_status_id": payload.todo_status_id},
        )
    todos = service.list_todos(db, todo.protocol_element_block_id)
    return next(item for item in todos if item.id == todo_id)


@router.post("/protocol-todos/{todo_id}/accept-tracked-change")
def accept_todo_tracked_change(
    todo_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """'Ausblenden' for one todo's red tracked-change highlight - keeps the todo, just
    stops marking it as changed/added/pending-delete."""
    require_writer(user)
    access_service.ensure_can_read_todo(db, user, todo_id)
    protocol_id = access_service.repository.protocol_id_for_todo(db, todo_id=todo_id)
    # Standalone todos (protocol_id None) have no tracked-change concept in practice, but
    # guard consistently with patch/delete above rather than special-casing this endpoint.
    if protocol_id:
        protocol_service.get_protocol_or_404_not_frozen(db, protocol_id)
    try:
        result = service.accept_tracked_change(db, todo_id)
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
    todo_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    access_service.ensure_can_read_todo(db, user, todo_id)
    protocol_id = access_service.repository.protocol_id_for_todo(db, todo_id=todo_id)
    # Standalone todos (protocol_id None) stay deletable regardless of any protocol status.
    protocol = protocol_service.get_protocol_or_404_not_frozen(db, protocol_id) if protocol_id else None
    track_changes_active = bool(protocol and protocol.status == "geplant" and protocol.track_changes_enabled)
    try:
        result = service.delete_todo(db, todo_id, track_changes_active=track_changes_active)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Todo could not be deleted") from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Todo not found")
    hard_deleted, block_id = result
    audit.log(db, action="todo.deleted", actor=user, entity_type="protocol_todo", entity_id=todo_id)
    if hard_deleted or block_id is None:
        return {"pending_delete": False, "message": "Todo deleted", "todo": None}
    todos = service.list_todos(db, block_id)
    todo_read = next((item for item in todos if item.id == todo_id), None)
    return {"pending_delete": True, "message": "Todo pending delete", "todo": todo_read}
