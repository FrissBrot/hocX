from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ProtocolTodo, TodoStatus


class ProtocolTodoRepository:
    def list_for_protocol_element(self, db: Session, protocol_element_id: int):
        query = (
            select(ProtocolTodo, TodoStatus.code.label("todo_status_code"))
            .join(TodoStatus, TodoStatus.id == ProtocolTodo.todo_status_id)
            .where(ProtocolTodo.protocol_element_id == protocol_element_id)
            .order_by(ProtocolTodo.sort_index.asc(), ProtocolTodo.id.asc())
        )
        return db.execute(query).all()

    def get(self, db: Session, todo_id: int) -> ProtocolTodo | None:
        return db.get(ProtocolTodo, todo_id)

    def next_sort_index(self, db: Session, protocol_element_id: int) -> int:
        current = db.scalar(
            select(func.max(ProtocolTodo.sort_index)).where(ProtocolTodo.protocol_element_id == protocol_element_id)
        )
        return 0 if current is None else int(current) + 1

    def create(self, db: Session, todo: ProtocolTodo) -> ProtocolTodo:
        db.add(todo)
        db.commit()
        db.refresh(todo)
        return todo

    def update(self, db: Session, todo: ProtocolTodo, values: dict) -> ProtocolTodo:
        for key, value in values.items():
            setattr(todo, key, value)
        db.add(todo)
        db.commit()
        db.refresh(todo)
        return todo

    def delete(self, db: Session, todo: ProtocolTodo) -> None:
        db.delete(todo)
        db.commit()
