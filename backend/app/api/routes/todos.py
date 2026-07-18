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
from app.services.protocol_todo_service import ProtocolTodoService

router = APIRouter()
service = ProtocolTodoService()
access_service = AccessService()


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
    """All todos for the tenant (admin) or only the user's assigned todos (non-admin)."""
    require_reader(user)
    can_admin = user.current_role == "admin"
    if can_admin:
        return service.list_todos_for_tenant(db, user.current_tenant_id, skip=skip, limit=limit)
    return service.list_todos_for_user(db, user.current_tenant_id, user.user_id, skip=skip, limit=limit)


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
    try:
        todo = service.create_todo(db, protocol_element_block_id, payload)
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
    require_writer(user)
    try:
        todo = service.update_todo(db, todo_id, payload)
    except (SQLAlchemyError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Todo could not be updated") from exc
    if todo is None:
        raise HTTPException(status_code=404, detail="Todo not found")
    todos = service.list_todos(db, todo.protocol_element_block_id)
    return next(item for item in todos if item.id == todo_id)


@router.delete("/protocol-todos/{todo_id}", response_model=dict[str, str])
def delete_todo(
    todo_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    try:
        deleted = service.delete_todo(db, todo_id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Todo could not be deleted") from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Todo not found")
    return {"message": "Todo deleted"}
