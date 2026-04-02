from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models import Event, Participant, Protocol, ProtocolElement, ProtocolElementBlock, ProtocolTodo, Template, TemplateParticipant, TodoStatus


class ProtocolTodoRepository:
    def list_for_protocol_block(self, db: Session, protocol_element_block_id: int):
        due_event = Event.__table__.alias("due_event")
        next_event = Event.__table__.alias("next_event")
        last_event = Event.__table__.alias("last_event")
        query = (
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
            )
            .join(TodoStatus, TodoStatus.id == ProtocolTodo.todo_status_id)
            .outerjoin(Participant, Participant.id == ProtocolTodo.assigned_participant_id)
            .join(ProtocolElementBlock, ProtocolElementBlock.id == ProtocolTodo.protocol_element_block_id)
            .join(ProtocolElement, ProtocolElement.id == ProtocolElementBlock.protocol_element_id)
            .join(Protocol, Protocol.id == ProtocolElement.protocol_id)
            .join(Template, Template.id == Protocol.template_id)
            .outerjoin(due_event, due_event.c.id == ProtocolTodo.due_event_id)
            .outerjoin(next_event, next_event.c.id == Template.next_event_id)
            .outerjoin(last_event, last_event.c.id == Template.last_event_id)
            .where(ProtocolTodo.protocol_element_block_id == protocol_element_block_id)
            .order_by(ProtocolTodo.sort_index.asc(), ProtocolTodo.id.asc())
        )
        return db.execute(query).all()

    def get(self, db: Session, todo_id: int) -> ProtocolTodo | None:
        return db.get(ProtocolTodo, todo_id)

    def next_sort_index(self, db: Session, protocol_element_block_id: int) -> int:
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
