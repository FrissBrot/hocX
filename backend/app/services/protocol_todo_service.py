from sqlalchemy.orm import Session

from app.models import ProtocolTodo
from app.repositories.protocol_todo_repository import ProtocolTodoRepository
from app.schemas.protocol import ProtocolTodoCreate, ProtocolTodoRead, ProtocolTodoUpdate


class ProtocolTodoService:
    def __init__(self, repository: ProtocolTodoRepository | None = None) -> None:
        self.repository = repository or ProtocolTodoRepository()

    def list_todos(self, db: Session, protocol_element_block_id: int) -> list[ProtocolTodoRead]:
        rows = self.repository.list_for_protocol_block(db, protocol_element_block_id)
        return [
            ProtocolTodoRead(
                **row.ProtocolTodo.__dict__,
                todo_status_code=row.todo_status_code,
            )
            for row in rows
        ]

    def create_todo(self, db: Session, protocol_element_block_id: int, payload: ProtocolTodoCreate) -> ProtocolTodo:
        todo = ProtocolTodo(
            protocol_element_block_id=protocol_element_block_id,
            sort_index=self.repository.next_sort_index(db, protocol_element_block_id),
            task=payload.task,
            assigned_user_id=payload.assigned_user_id,
            todo_status_id=payload.todo_status_id,
            due_date=payload.due_date,
            reference_link=payload.reference_link,
            created_by=payload.created_by,
        )
        return self.repository.create(db, todo)

    def update_todo(self, db: Session, todo_id: int, payload: ProtocolTodoUpdate):
        todo = self.repository.get(db, todo_id)
        if todo is None:
            return None
        values = payload.model_dump(exclude_unset=True)
        if not values:
            return todo
        return self.repository.update(db, todo, values)

    def delete_todo(self, db: Session, todo_id: int) -> bool:
        todo = self.repository.get(db, todo_id)
        if todo is None:
            return False
        self.repository.delete(db, todo)
        return True
