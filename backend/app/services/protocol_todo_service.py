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
                assigned_participant_name=row.assigned_participant_name,
                due_event_title=row.due_event_title,
                due_event_date=row.due_event_date,
                resolved_due_date=row.resolved_due_date,
                resolved_due_label=row.resolved_due_label,
            )
            for row in rows
        ]

    def _normalize_due_fields(self, values: dict) -> dict:
        if values.get("due_marker"):
            values["due_event_id"] = None
            if "due_date" not in values or values.get("due_date") is None:
                values["due_date"] = None
        elif values.get("due_event_id") is not None:
            values["due_marker"] = None
            values["due_date"] = None
        elif "due_date" in values and values.get("due_date") is not None:
            values["due_event_id"] = None
            values["due_marker"] = None
        return values

    def create_todo(self, db: Session, protocol_element_block_id: int, payload: ProtocolTodoCreate) -> ProtocolTodo:
        if payload.assigned_participant_id is not None and not self.repository.participant_allowed_for_block(
            db,
            protocol_element_block_id,
            payload.assigned_participant_id,
        ):
            raise ValueError("Assigned participant is not available for this template")
        if payload.due_event_id is not None and not self.repository.event_allowed_for_block(
            db,
            protocol_element_block_id,
            payload.due_event_id,
        ):
            raise ValueError("Due event is not available for this tenant")
        values = self._normalize_due_fields(payload.model_dump())
        todo = ProtocolTodo(
            protocol_element_block_id=protocol_element_block_id,
            sort_index=self.repository.next_sort_index(db, protocol_element_block_id),
            task=payload.task,
            assigned_user_id=payload.assigned_user_id,
            assigned_participant_id=payload.assigned_participant_id,
            todo_status_id=payload.todo_status_id,
            due_date=values.get("due_date"),
            due_event_id=values.get("due_event_id"),
            due_marker=values.get("due_marker"),
            reference_link=payload.reference_link,
            created_by=payload.created_by,
        )
        return self.repository.create(db, todo)

    def update_todo(self, db: Session, todo_id: int, payload: ProtocolTodoUpdate):
        todo = self.repository.get(db, todo_id)
        if todo is None:
            return None
        values = payload.model_dump(exclude_unset=True)
        values = self._normalize_due_fields(values)
        participant_id = values.get("assigned_participant_id")
        if participant_id is not None and not self.repository.participant_allowed_for_block(db, todo.protocol_element_block_id, participant_id):
            raise ValueError("Assigned participant is not available for this template")
        due_event_id = values.get("due_event_id")
        if due_event_id is not None and not self.repository.event_allowed_for_block(db, todo.protocol_element_block_id, due_event_id):
            raise ValueError("Due event is not available for this tenant")
        if not values:
            return todo
        return self.repository.update(db, todo, values)

    def delete_todo(self, db: Session, todo_id: int) -> bool:
        todo = self.repository.get(db, todo_id)
        if todo is None:
            return False
        self.repository.delete(db, todo)
        return True
