from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.models import ElementType, Event, Participant, Protocol, ProtocolElement, ProtocolElementBlock, ProtocolTodo, Template, TemplateParticipant, TodoStatus


class ProtocolTodoRepository:
    def _base_todo_query(self):
        """Shared SELECT + JOIN base used by all list queries."""
        due_event = Event.__table__.alias("due_event")
        next_event = Event.__table__.alias("next_event")
        last_event = Event.__table__.alias("last_event")
        return (
            select(
                ProtocolTodo,
                TodoStatus.code.label("todo_status_code"),
                Participant.display_name.label("assigned_participant_name"),
                due_event.c.title.label("due_event_title"),
                due_event.c.event_date.label("due_event_date"),
                case(
                    (ProtocolTodo.due_date.is_not(None), ProtocolTodo.due_date),
                    (ProtocolTodo.due_event_id.is_not(None), due_event.c.event_date),
                    (ProtocolTodo.due_marker == "next_session", next_event.c.event_date),
                    (ProtocolTodo.due_marker == "last_session", last_event.c.event_date),
                    else_=None,
                ).label("resolved_due_date"),
                case(
                    (ProtocolTodo.due_event_id.is_not(None), due_event.c.title),
                    (ProtocolTodo.due_marker == "next_session", "naechste Sitzung"),
                    (ProtocolTodo.due_marker == "last_session", "letzte Sitzung"),
                    else_=None,
                ).label("resolved_due_label"),
                Protocol.id.label("protocol_id"),
                Protocol.protocol_number.label("protocol_number"),
                Protocol.protocol_date.label("protocol_date"),
                Protocol.title.label("protocol_title"),
                Protocol.status.label("protocol_status"),
                ProtocolElementBlock.block_title_snapshot.label("block_title"),
            )
            .join(TodoStatus, TodoStatus.id == ProtocolTodo.todo_status_id)
            .outerjoin(Participant, Participant.id == ProtocolTodo.assigned_participant_id)
            .outerjoin(ProtocolElementBlock, ProtocolElementBlock.id == ProtocolTodo.protocol_element_block_id)
            .outerjoin(ProtocolElement, ProtocolElement.id == ProtocolElementBlock.protocol_element_id)
            .outerjoin(Protocol, Protocol.id == ProtocolElement.protocol_id)
            .outerjoin(Template, Template.id == Protocol.template_id)
            .outerjoin(due_event, due_event.c.id == ProtocolTodo.due_event_id)
            .outerjoin(next_event, next_event.c.id == Template.next_event_id)
            .outerjoin(last_event, last_event.c.id == Template.last_event_id)
        ), due_event, next_event, last_event

    def list_for_tenant(self, db: Session, tenant_id: int, skip: int = 0, limit: int = 100):
        query, *_ = self._base_todo_query()
        query = query.where(
            or_(Protocol.tenant_id == tenant_id, ProtocolTodo.tenant_id == tenant_id)
        ).order_by(
            ProtocolTodo.todo_status_id.asc(),
            Protocol.protocol_date.desc(),
            ProtocolTodo.sort_index.asc(),
        ).offset(skip).limit(limit)
        return db.execute(query).all()

    def list_for_user(self, db: Session, tenant_id: int, user_id: int, skip: int = 0, limit: int = 100):
        # Inline subquery avoids a separate round-trip to find the linked participant
        linked_participant_subq = (
            select(Participant.id)
            .where(Participant.app_user_id == user_id, Participant.tenant_id == tenant_id)
            .limit(1)
            .scalar_subquery()
        )
        query, *_ = self._base_todo_query()
        query = query.where(
            or_(Protocol.tenant_id == tenant_id, ProtocolTodo.tenant_id == tenant_id)
        ).where(
            or_(
                ProtocolTodo.assigned_user_id == user_id,
                ProtocolTodo.assigned_participant_id == linked_participant_subq,
            )
        ).order_by(
            ProtocolTodo.todo_status_id.asc(),
            Protocol.protocol_date.desc(),
            ProtocolTodo.sort_index.asc(),
        ).offset(skip).limit(limit)
        return db.execute(query).all()

    def list_for_protocols_or_assigned(
        self, db: Session, tenant_id: int, protocol_ids: list[int], user_id: int, skip: int = 0, limit: int = 100
    ):
        """Restricted-reader view: todos from protocols the user has access to, plus anything
        directly assigned to them (covers standalone tenant todos with no protocol link)."""
        linked_participant_subq = (
            select(Participant.id)
            .where(Participant.app_user_id == user_id, Participant.tenant_id == tenant_id)
            .limit(1)
            .scalar_subquery()
        )
        conditions = [
            ProtocolTodo.assigned_user_id == user_id,
            ProtocolTodo.assigned_participant_id == linked_participant_subq,
        ]
        if protocol_ids:
            conditions.append(Protocol.id.in_(protocol_ids))
        query, *_ = self._base_todo_query()
        query = query.where(
            or_(Protocol.tenant_id == tenant_id, ProtocolTodo.tenant_id == tenant_id)
        ).where(
            or_(*conditions)
        ).order_by(
            ProtocolTodo.todo_status_id.asc(),
            Protocol.protocol_date.desc(),
            ProtocolTodo.sort_index.asc(),
        ).offset(skip).limit(limit)
        return db.execute(query).all()

    def list_for_protocol_block(self, db: Session, protocol_element_block_id: int):
        query, *_ = self._base_todo_query()
        query = query.where(
            ProtocolTodo.protocol_element_block_id == protocol_element_block_id
        ).order_by(ProtocolTodo.sort_index.asc(), ProtocolTodo.id.asc())
        return db.execute(query).all()

    def list_pending_for_protocol(self, db: Session, protocol_id: int, template_id: int, protocol_date):
        """Session todos from strictly earlier protocols of the same template (all statuses).
        'Earlier' = older date, or same date with lower protocol ID."""
        query, *_ = self._base_todo_query()
        query = (
            query
            .where(
                Protocol.template_id == template_id,
                ProtocolElement.section_name_snapshot == "Sitzungsnotizen",
                or_(
                    Protocol.protocol_date < protocol_date,
                    (Protocol.protocol_date == protocol_date) & (Protocol.id < protocol_id),
                ),
            )
            .order_by(Protocol.protocol_date.desc(), ProtocolTodo.sort_index.asc())
        )
        return db.execute(query).all()

    def get(self, db: Session, todo_id: int) -> ProtocolTodo | None:
        return db.get(ProtocolTodo, todo_id)

    def next_sort_index(self, db: Session, protocol_element_block_id: int | None) -> int:
        if protocol_element_block_id is None:
            current = db.scalar(
                select(func.max(ProtocolTodo.sort_index)).where(ProtocolTodo.protocol_element_block_id.is_(None))
            )
        else:
            current = db.scalar(
                select(func.max(ProtocolTodo.sort_index)).where(ProtocolTodo.protocol_element_block_id == protocol_element_block_id)
            )
        return 0 if current is None else int(current) + 1

    def participant_allowed_for_block(self, db: Session, protocol_element_block_id: int, participant_id: int) -> bool:
        statement = (
            select(func.count(TemplateParticipant.participant_id))
            .join(Protocol, Protocol.template_id == TemplateParticipant.template_id)
            .join(ProtocolElement, ProtocolElement.protocol_id == Protocol.id)
            .join(ProtocolElementBlock, ProtocolElementBlock.protocol_element_id == ProtocolElement.id)
            .where(ProtocolElementBlock.id == protocol_element_block_id)
            .where(TemplateParticipant.participant_id == participant_id)
        )
        return bool(db.scalar(statement))

    def event_allowed_for_block(self, db: Session, protocol_element_block_id: int, event_id: int) -> bool:
        statement = (
            select(func.count(Event.id))
            .join(Protocol, Protocol.tenant_id == Event.tenant_id)
            .join(ProtocolElement, ProtocolElement.protocol_id == Protocol.id)
            .join(ProtocolElementBlock, ProtocolElementBlock.protocol_element_id == ProtocolElement.id)
            .where(ProtocolElementBlock.id == protocol_element_block_id)
            .where(Event.id == event_id)
        )
        return bool(db.scalar(statement))

    def list_todo_blocks(self, db: Session, tenant_id: int):
        """Return all protocol-element blocks of type 'todo' for a tenant, ordered by protocol date desc."""
        return db.execute(
            select(
                ProtocolElementBlock.id.label("block_id"),
                ProtocolElementBlock.block_title_snapshot.label("block_title"),
                Protocol.id.label("protocol_id"),
                Protocol.protocol_number.label("protocol_number"),
                Protocol.title.label("protocol_title"),
                Protocol.protocol_date.label("protocol_date"),
            )
            .join(ProtocolElement, ProtocolElement.id == ProtocolElementBlock.protocol_element_id)
            .join(Protocol, Protocol.id == ProtocolElement.protocol_id)
            .join(ElementType, ElementType.id == ProtocolElementBlock.element_type_id)
            .where(Protocol.tenant_id == tenant_id)
            .where(ElementType.code == "todo")
            .order_by(Protocol.protocol_date.desc(), Protocol.id.desc())
        ).all()

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
