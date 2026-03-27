from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.db import get_db
from app.schemas.protocol import ProtocolTodoCreate, ProtocolTodoRead, ProtocolTodoUpdate
from app.services.protocol_todo_service import ProtocolTodoService

router = APIRouter()
service = ProtocolTodoService()


@router.get("/protocol-elements/{protocol_element_id}/todos", response_model=list[ProtocolTodoRead])
def list_todos(protocol_element_id: int, db: Session = Depends(get_db)):
    return service.list_todos(db, protocol_element_id)


@router.post(
    "/protocol-elements/{protocol_element_id}/todos",
    response_model=ProtocolTodoRead,
    status_code=status.HTTP_201_CREATED,
)
def create_todo(protocol_element_id: int, payload: ProtocolTodoCreate, db: Session = Depends(get_db)):
    try:
        todo = service.create_todo(db, protocol_element_id, payload)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Todo could not be created") from exc
    todos = service.list_todos(db, protocol_element_id)
    return next(item for item in todos if item.id == todo.id)


@router.patch("/protocol-todos/{todo_id}", response_model=ProtocolTodoRead)
def patch_todo(todo_id: int, payload: ProtocolTodoUpdate, db: Session = Depends(get_db)):
    try:
        todo = service.update_todo(db, todo_id, payload)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Todo could not be updated") from exc
    if todo is None:
        raise HTTPException(status_code=404, detail="Todo not found")
    todos = service.list_todos(db, todo.protocol_element_id)
    return next(item for item in todos if item.id == todo_id)


@router.delete("/protocol-todos/{todo_id}", response_model=dict[str, str])
def delete_todo(todo_id: int, db: Session = Depends(get_db)):
    try:
        deleted = service.delete_todo(db, todo_id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Todo could not be deleted") from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Todo not found")
    return {"message": "Todo deleted"}
