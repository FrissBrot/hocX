from sqlalchemy.orm import Session

from app.models import ProtocolTodo
from app.repositories.protocol_todo_repository import ProtocolTodoRepository
from app.schemas.protocol import ProtocolTodoCreate, ProtocolTodoRead, ProtocolTodoUpdate, TodoListItem


class ProtocolTodoService:
    def __init__(self, repository: ProtocolTodoRepository | None = None) -> None:
        self.repository = repository or ProtocolTodoRepository()

    def list_todos(self, db: Session, protocol_element_block_id: int) -> list[ProtocolTodoRead]:
        rows = self.repository.list_for_protocol_block(db, protocol_element_block_id)
        return [self._row_to_todo_read(row) for row in rows]

    def _common_fields(self, row) -> dict:
        return {
            **row.ProtocolTodo.__dict__,
            "todo_status_code": row.todo_status_code,
            "assigned_participant_name": row.assigned_participant_name,
            "due_event_title": row.due_event_title,
            "due_event_date": row.due_event_date,
            "resolved_due_date": row.resolved_due_date,
            "resolved_due_label": row.resolved_due_label,
        }

    def _row_to_todo_read(self, row) -> ProtocolTodoRead:
        return ProtocolTodoRead(**self._common_fields(row))

    def _row_to_list_item(self, row) -> TodoListItem:
        return TodoListItem(
            **self._common_fields(row),
            protocol_id=row.protocol_id,
            protocol_number=row.protocol_number,
            protocol_date=row.protocol_date,
            protocol_title=row.protocol_title,
            protocol_status=row.protocol_status,
            block_title=row.block_title,
        )

    def list_todo_blocks(self, db: Session, tenant_id: int) -> list[dict]:
        rows = self.repository.list_todo_blocks(db, tenant_id)
        return [
            {
                "block_id": row.block_id,
                "block_title": row.block_title,
                "protocol_id": row.protocol_id,
                "protocol_number": row.protocol_number,
                "protocol_title": row.protocol_title,
                "protocol_date": str(row.protocol_date),
            }
            for row in rows
        ]

    def list_todos_for_tenant(self, db: Session, tenant_id: int, skip: int = 0, limit: int = 100) -> list[TodoListItem]:
        rows = self.repository.list_for_tenant(db, tenant_id, skip=skip, limit=limit)
        return [self._row_to_list_item(row) for row in rows]

    def list_todos_for_user(self, db: Session, tenant_id: int, user_id: int, skip: int = 0, limit: int = 100) -> list[TodoListItem]:
        rows = self.repository.list_for_user(db, tenant_id, user_id, skip=skip, limit=limit)
        return [self._row_to_list_item(row) for row in rows]

    def list_todos_for_protocols_or_assigned(
        self, db: Session, tenant_id: int, protocol_ids: list[int], user_id: int, skip: int = 0, limit: int = 100
    ) -> list[TodoListItem]:
        rows = self.repository.list_for_protocols_or_assigned(db, tenant_id, protocol_ids, user_id, skip=skip, limit=limit)
        return [self._row_to_list_item(row) for row in rows]

    def list_pending_for_protocol(self, db: Session, protocol_id: int, template_id: int, protocol_date) -> list[TodoListItem]:
        rows = self.repository.list_pending_for_protocol(db, protocol_id, template_id, protocol_date)
        return [self._row_to_list_item(row) for row in rows]

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

    def create_standalone_todo(self, db: Session, tenant_id: int, payload: ProtocolTodoCreate) -> ProtocolTodo:
        values = self._normalize_due_fields(payload.model_dump())
        todo = ProtocolTodo(
            tenant_id=tenant_id,
            protocol_element_block_id=None,
            sort_index=self.repository.next_sort_index(db, None),
            task=payload.task,
            assigned_user_id=payload.assigned_user_id,
            assigned_participant_id=payload.assigned_participant_id,
            todo_status_id=payload.todo_status_id,
            due_date=values.get("due_date"),
            due_event_id=values.get("due_event_id"),
            due_marker=values.get("due_marker"),
            reference_link=payload.reference_link,
            tags=payload.tags,
            created_by=payload.created_by,
        )
        return self.repository.create(db, todo)

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
            tags=payload.tags,
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
