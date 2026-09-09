from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AppUser, Event, Participant, Protocol, ProtocolElementBlock, ProtocolTodo, SubmissionAssignment, TodoStatus
from app.repositories.protocol_todo_repository import ProtocolTodoRepository
from app.schemas.protocol import ProtocolTodoCreate, ProtocolTodoRead, ProtocolTodoUpdate, TodoListItem
from app.services import public_id_service

# Status codes that count as "closed"/completed for completed_at purposes - mirrors the
# closed_status_ids grouping used elsewhere (e.g. ProtocolService._open_todos_for_template_block)
# and the "done" bucket the statistics/chart services derive from completed_at.
_COMPLETED_STATUS_CODES = ("done", "cancelled")


class ProtocolTodoService:
    def __init__(self, repository: ProtocolTodoRepository | None = None) -> None:
        self.repository = repository or ProtocolTodoRepository()

    def list_todos(self, db: Session, protocol_element_block_id: int) -> list[ProtocolTodoRead]:
        rows = self.repository.list_for_protocol_block(db, protocol_element_block_id)
        return [self._row_to_todo_read(db, row) for row in rows]

    def _common_fields(self, db: Session, row) -> dict:
        todo = row.ProtocolTodo
        return {
            **todo.__dict__,
            "id": todo.public_id,
            "protocol_element_block_id": public_id_service.resolve_public_id(db, ProtocolElementBlock, todo.protocol_element_block_id)
            if todo.protocol_element_block_id is not None
            else None,
            "assigned_user_id": public_id_service.resolve_public_id(db, AppUser, todo.assigned_user_id)
            if todo.assigned_user_id is not None
            else None,
            "assigned_participant_id": public_id_service.resolve_public_id(db, Participant, todo.assigned_participant_id)
            if todo.assigned_participant_id is not None
            else None,
            "due_event_id": public_id_service.resolve_public_id(db, Event, todo.due_event_id)
            if todo.due_event_id is not None
            else None,
            "created_by": public_id_service.resolve_public_id(db, AppUser, todo.created_by) if todo.created_by is not None else None,
            "closed_in_protocol_id": public_id_service.resolve_public_id(db, Protocol, todo.closed_in_protocol_id)
            if todo.closed_in_protocol_id is not None
            else None,
            "submission_assignment_id": public_id_service.resolve_public_id(db, SubmissionAssignment, todo.submission_assignment_id)
            if todo.submission_assignment_id is not None
            else None,
            "todo_status_code": row.todo_status_code,
            "assigned_participant_name": row.assigned_participant_name,
            "due_event_title": row.due_event_title,
            "due_event_date": row.due_event_date,
            "resolved_due_date": row.resolved_due_date,
            "resolved_due_label": row.resolved_due_label,
        }

    def _row_to_todo_read(self, db: Session, row) -> ProtocolTodoRead:
        return ProtocolTodoRead(**self._common_fields(db, row))

    def _row_to_list_item(self, db: Session, row) -> TodoListItem:
        return TodoListItem(
            **self._common_fields(db, row),
            protocol_id=public_id_service.resolve_public_id(db, Protocol, row.protocol_id) if row.protocol_id is not None else None,
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
        return [self._row_to_list_item(db, row) for row in rows]

    def list_todos_for_user(self, db: Session, tenant_id: int, user_id: int, skip: int = 0, limit: int = 100) -> list[TodoListItem]:
        rows = self.repository.list_for_user(db, tenant_id, user_id, skip=skip, limit=limit)
        return [self._row_to_list_item(db, row) for row in rows]

    def list_todos_for_protocols_or_assigned(
        self, db: Session, tenant_id: int, protocol_ids: list[int], user_id: int, skip: int = 0, limit: int = 100
    ) -> list[TodoListItem]:
        rows = self.repository.list_for_protocols_or_assigned(db, tenant_id, protocol_ids, user_id, skip=skip, limit=limit)
        return [self._row_to_list_item(db, row) for row in rows]

    def list_pending_for_protocol(self, db: Session, protocol_id: int, template_id: int, protocol_date) -> list[TodoListItem]:
        rows = self.repository.list_pending_for_protocol(db, protocol_id, template_id, protocol_date)
        return [self._row_to_list_item(db, row) for row in rows]

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
        # assigned_participant_id/due_event_id/assigned_user_id arrive as public UUIDs -
        # resolve to internal ids first (unscoped; the *_allowed_for_tenant checks right
        # below are the actual authorization boundary, unchanged from before this migration
        # - see their docstrings, e.g. audit D6 2026-08-16 for why they exist at all).
        assigned_participant_id = public_id_service.resolve_internal_id(db, Participant, payload.assigned_participant_id) if payload.assigned_participant_id else None
        due_event_id = public_id_service.resolve_internal_id(db, Event, payload.due_event_id) if payload.due_event_id else None
        assigned_user_id = public_id_service.resolve_internal_id(db, AppUser, payload.assigned_user_id) if payload.assigned_user_id else None
        created_by = public_id_service.resolve_internal_id(db, AppUser, payload.created_by) if payload.created_by else None
        if payload.assigned_participant_id is not None and (
            assigned_participant_id is None or not self.repository.participant_allowed_for_tenant(db, tenant_id, assigned_participant_id)
        ):
            raise ValueError("Assigned participant is not available for this tenant")
        if payload.due_event_id is not None and (
            due_event_id is None or not self.repository.event_allowed_for_tenant(db, tenant_id, due_event_id)
        ):
            raise ValueError("Due event is not available for this tenant")
        if payload.assigned_user_id is not None and (
            assigned_user_id is None or not self.repository.user_allowed_for_tenant(db, tenant_id, assigned_user_id)
        ):
            raise ValueError("Assigned user is not available for this tenant")
        values = self._normalize_due_fields(payload.model_dump())
        todo = ProtocolTodo(
            tenant_id=tenant_id,
            protocol_element_block_id=None,
            sort_index=self.repository.next_sort_index(db, None),
            task=payload.task,
            assigned_user_id=assigned_user_id,
            assigned_participant_id=assigned_participant_id,
            todo_status_id=payload.todo_status_id,
            due_date=values.get("due_date"),
            due_event_id=due_event_id,
            due_marker=values.get("due_marker"),
            reference_link=payload.reference_link,
            tags=payload.tags,
            created_by=created_by,
        )
        return self.repository.create(db, todo)

    def create_todo(
        self, db: Session, protocol_element_block_id: int, payload: ProtocolTodoCreate, *, track_changes_active: bool = False
    ) -> ProtocolTodo:
        assigned_participant_id = public_id_service.resolve_internal_id(db, Participant, payload.assigned_participant_id) if payload.assigned_participant_id else None
        due_event_id = public_id_service.resolve_internal_id(db, Event, payload.due_event_id) if payload.due_event_id else None
        assigned_user_id = public_id_service.resolve_internal_id(db, AppUser, payload.assigned_user_id) if payload.assigned_user_id else None
        created_by = public_id_service.resolve_internal_id(db, AppUser, payload.created_by) if payload.created_by else None
        if payload.assigned_participant_id is not None and (
            assigned_participant_id is None
            or not self.repository.participant_allowed_for_block(db, protocol_element_block_id, assigned_participant_id)
        ):
            raise ValueError("Assigned participant is not available for this template")
        if payload.due_event_id is not None and (
            due_event_id is None or not self.repository.event_allowed_for_block(db, protocol_element_block_id, due_event_id)
        ):
            raise ValueError("Due event is not available for this tenant")
        if payload.assigned_user_id is not None:
            tenant_id = self.repository.tenant_id_for_block(db, protocol_element_block_id)
            if tenant_id is None or assigned_user_id is None or not self.repository.user_allowed_for_tenant(db, tenant_id, assigned_user_id):
                raise ValueError("Assigned user is not available for this tenant")
        values = self._normalize_due_fields(payload.model_dump())
        todo = ProtocolTodo(
            protocol_element_block_id=protocol_element_block_id,
            sort_index=self.repository.next_sort_index(db, protocol_element_block_id),
            task=payload.task,
            assigned_user_id=assigned_user_id,
            assigned_participant_id=assigned_participant_id,
            todo_status_id=payload.todo_status_id,
            due_date=values.get("due_date"),
            due_event_id=due_event_id,
            due_marker=values.get("due_marker"),
            reference_link=payload.reference_link,
            tags=payload.tags,
            created_by=created_by,
            tracked_change="added" if track_changes_active else None,
        )
        return self.repository.create(db, todo)

    def update_todo(self, db: Session, todo_id: int, payload: ProtocolTodoUpdate, *, track_changes_active: bool = False):
        todo = self.repository.get(db, todo_id)
        if todo is None:
            return None
        values = payload.model_dump(exclude_unset=True)
        values = self._normalize_due_fields(values)
        # assigned_participant_id/due_event_id/assigned_user_id/closed_in_protocol_id arrive
        # as public UUIDs - resolve to internal ids in place before any of the checks/DB
        # writes below, which all expect internal ints. Unscoped resolution here is fine -
        # the *_allowed_for_* checks right below are the actual authorization boundary.
        for field, model in (
            ("assigned_participant_id", Participant),
            ("due_event_id", Event),
            ("assigned_user_id", AppUser),
            ("closed_in_protocol_id", Protocol),
        ):
            if field in values and values[field] is not None:
                resolved = public_id_service.resolve_internal_id(db, model, values[field])
                values[field] = resolved if resolved is not None else -1  # sentinel: fails the ownership check below
        # Standalone todos (protocol_element_block_id is None) must use the tenant-scoped
        # checks, not the block-scoped ones - the block-scoped queries INNER JOIN through
        # ProtocolElementBlock.id == protocol_element_block_id, which can never match NULL,
        # so every assignment to a standalone todo failed unconditionally before this fix
        # (audit D5, 2026-08-16).
        is_standalone = todo.protocol_element_block_id is None
        participant_id = values.get("assigned_participant_id")
        if participant_id is not None:
            allowed = (
                self.repository.participant_allowed_for_tenant(db, todo.tenant_id, participant_id)
                if is_standalone
                else self.repository.participant_allowed_for_block(db, todo.protocol_element_block_id, participant_id)
            )
            if not allowed:
                raise ValueError("Assigned participant is not available for this template")
        due_event_id = values.get("due_event_id")
        if due_event_id is not None:
            allowed = (
                self.repository.event_allowed_for_tenant(db, todo.tenant_id, due_event_id)
                if is_standalone
                else self.repository.event_allowed_for_block(db, todo.protocol_element_block_id, due_event_id)
            )
            if not allowed:
                raise ValueError("Due event is not available for this tenant")
        # assigned_user_id/closed_in_protocol_id were, unlike the two checks above, never
        # validated against the tenant at all (audit finding, 2026-08-25) - a writer could
        # assign a todo to an arbitrary app_user.id or close it "in" an arbitrary,
        # potentially cross-tenant protocol_id.
        assigned_user_id = values.get("assigned_user_id")
        closed_in_protocol_id = values.get("closed_in_protocol_id")
        if assigned_user_id is not None or closed_in_protocol_id is not None:
            tenant_id = todo.tenant_id if is_standalone else self.repository.tenant_id_for_block(db, todo.protocol_element_block_id)
            if tenant_id is None:
                raise ValueError("Todo has no resolvable tenant")
            if assigned_user_id is not None and not self.repository.user_allowed_for_tenant(db, tenant_id, assigned_user_id):
                raise ValueError("Assigned user is not available for this tenant")
            if closed_in_protocol_id is not None and not self.repository.protocol_allowed_for_tenant(db, tenant_id, closed_in_protocol_id):
                raise ValueError("closed_in_protocol_id is not available for this tenant")
        # completed_at is server-authoritative and derived solely from the status
        # transition: a client-supplied value is always ignored/overridden here so
        # statistics/charts (which key off completed_at) can't drift from the actual
        # todo_status_id - e.g. reopening a "done" todo without the client explicitly
        # clearing completed_at must not leave it counted as done.
        if "todo_status_id" in values:
            new_status_code = db.scalar(select(TodoStatus.code).where(TodoStatus.id == values["todo_status_id"]))
            if new_status_code is None:
                raise ValueError("Unknown todo status")
            values["completed_at"] = datetime.now(timezone.utc) if new_status_code in _COMPLETED_STATUS_CODES else None
        else:
            values.pop("completed_at", None)
        if not values:
            return todo
        # Only task/tags count as "content" for marking purposes (assignee/due-date/status
        # are workflow metadata, not something a reviewer needs to see red-marked). The
        # original values are pinned exactly once - a todo already marked "added" or
        # "changed" keeps its first-captured before-value across any number of further edits.
        if track_changes_active and todo.tracked_change is None and ("task" in values or "tags" in values):
            values["tracked_change"] = "changed"
            values["tracked_change_before_json"] = {"task": todo.task, "tags": todo.tags}
        return self.repository.update(db, todo, values)

    def accept_tracked_change(self, db: Session, todo_id: int) -> tuple[bool, int | None] | None:
        """'Ausblenden' for one todo's tracked-change highlight: permanently accepts its
        current state as the new normal, independent of the protocol-wide clear that
        otherwise only happens at vorbereitet -> durchgefuehrt. Returns None if not found,
        else (hard_deleted, protocol_element_block_id) - mirrors delete_todo's shape. A
        pending-delete ghost is hard-deleted now, finalizing the removal early."""
        todo = self.repository.get(db, todo_id)
        if todo is None:
            return None
        block_id = todo.protocol_element_block_id
        if todo.pending_delete:
            self.repository.delete(db, todo)
            return True, block_id
        if todo.tracked_change is not None or todo.tracked_change_before_json is not None:
            self.repository.update(db, todo, {"tracked_change": None, "tracked_change_before_json": None})
        return False, block_id

    def delete_todo(self, db: Session, todo_id: int, *, track_changes_active: bool = False) -> tuple[bool, int | None] | None:
        """Returns None if not found, else (hard_deleted, protocol_element_block_id). A
        todo created during this same tracked window has no accepted history to preserve,
        so it hard-deletes immediately; a pre-existing todo is soft-deleted (pending_delete)
        instead, so it can render struck-through until tracking is cleared."""
        todo = self.repository.get(db, todo_id)
        if todo is None:
            return None
        block_id = todo.protocol_element_block_id
        if track_changes_active and todo.tracked_change != "added":
            self.repository.update(db, todo, {"pending_delete": True})
            return False, block_id
        self.repository.delete(db, todo)
        return True, block_id
