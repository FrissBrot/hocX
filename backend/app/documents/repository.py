"""Datenzugriff der Dokument-Engine auf Protokollinhalte (aus dem früheren ExportRepository).

Abgeschlossene Protokolle lesen Todos aus ihrem eingefrorenen Stand (``todos_snapshot_json``),
offene Protokolle live - gleiche Regel wie ProtocolTodoService.frozen_snapshot."""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models import (
    Event,
    Participant,
    Protocol,
    ProtocolElement,
    ProtocolElementBlock,
    ProtocolImage,
    ProtocolText,
    ProtocolTodo,
    StoredFile,
    Template,
    TodoStatus,
)


def list_protocol_elements(db: Session, protocol_id: int) -> list[ProtocolElement]:
    return list(db.scalars(select(ProtocolElement).where(ProtocolElement.protocol_id == protocol_id).order_by(ProtocolElement.sort_index.asc())))


def list_element_blocks(db: Session, protocol_element_id: int) -> list[ProtocolElementBlock]:
    return list(
        db.scalars(
            select(ProtocolElementBlock)
            .where(ProtocolElementBlock.protocol_element_id == protocol_element_id)
            .order_by(ProtocolElementBlock.sort_index.asc(), ProtocolElementBlock.id.asc())
        )
    )


def get_protocol_text(db: Session, block_id: int) -> ProtocolText | None:
    return db.scalar(select(ProtocolText).where(ProtocolText.protocol_element_block_id == block_id))


def list_protocol_images(db: Session, block_id: int):
    return db.execute(
        select(ProtocolImage, StoredFile)
        .join(StoredFile, StoredFile.id == ProtocolImage.stored_file_id)
        .where(ProtocolImage.protocol_element_block_id == block_id)
        .order_by(ProtocolImage.sort_index.asc())
    ).all()


def _frozen_todo_snapshot(protocol: Protocol | None) -> dict | None:
    if protocol is None or protocol.status != "abgeschlossen":
        return None
    snapshot = protocol.todos_snapshot_json
    return snapshot if isinstance(snapshot, dict) else None


def _snapshot_rows(items: list[dict]) -> list[SimpleNamespace]:
    rows = []
    for item in items:
        due = item.get("resolved_due_date")
        rows.append(SimpleNamespace(
            ProtocolTodo=SimpleNamespace(task=item.get("task") or "", tags=item.get("tags") or []),
            todo_status_code=item.get("todo_status_code"),
            assigned_participant_name=item.get("assigned_participant_name"),
            due_event_title=item.get("due_event_title"),
            resolved_due_date=date.fromisoformat(due) if due else None,
            resolved_due_label=item.get("resolved_due_label"),
        ))
    return rows


def _todo_query():
    due_event = Event.__table__.alias("due_event")
    next_event = Event.__table__.alias("next_event")
    last_event = Event.__table__.alias("last_event")
    return (
        select(
            ProtocolTodo,
            TodoStatus.code.label("todo_status_code"),
            Participant.display_name.label("assigned_participant_name"),
            due_event.c.title.label("due_event_title"),
            case(
                (ProtocolTodo.due_date.is_not(None), ProtocolTodo.due_date),
                (ProtocolTodo.due_event_id.is_not(None), due_event.c.event_date),
                (ProtocolTodo.due_marker == "next_session", next_event.c.event_date),
                (ProtocolTodo.due_marker == "last_session", last_event.c.event_date),
                else_=None,
            ).label("resolved_due_date"),
            case(
                (ProtocolTodo.due_event_id.is_not(None), due_event.c.title),
                (ProtocolTodo.due_marker == "next_session", "nächste Sitzung"),
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
        .where(ProtocolTodo.pending_delete.is_(False))
    )


def list_block_todos(db: Session, protocol: Protocol, block_id: int):
    snapshot = _frozen_todo_snapshot(protocol)
    if snapshot is not None:
        return _snapshot_rows((snapshot.get("blocks") or {}).get(str(block_id)) or [])
    return db.execute(_todo_query().where(ProtocolTodo.protocol_element_block_id == block_id).order_by(ProtocolTodo.sort_index.asc())).all()


def list_todos_by_tag(db: Session, protocol: Protocol, tag: str):
    snapshot = _frozen_todo_snapshot(protocol)
    if snapshot is not None:
        items = [item for block in (snapshot.get("blocks") or {}).values() for item in block if tag in (item.get("tags") or [])]
        items.sort(key=lambda item: item.get("sort_index") or 0)
        return _snapshot_rows(items)
    return db.execute(
        _todo_query()
        .where(Protocol.id == protocol.id)
        .where(ProtocolTodo.tags.op("@>")(func.jsonb_build_array(tag)))
        .order_by(ProtocolTodo.sort_index.asc())
    ).all()


class ProtocolContent:
    """Alle Inhalte eines Protokolls für einen PDF-Aufbau, in einer festen Zahl von Abfragen:
    Punkte, Blöcke, Texte, Bilder und Aufgaben (live oder aus dem eingefrorenen Stand). Vorher
    fragten die Provider je Punkt und Block einzeln (N+1, tests/test_query_budget.py).

    Gleiche Ergebnisse wie die Einzelfunktionen oben (list_element_blocks, get_protocol_text,
    list_protocol_images, list_block_todos, list_todos_by_tag); ein Block, der nicht zu diesem
    Protokoll gehört, fällt auf die Einzelabfrage zurück. Gültig für einen Aufbau
    (BuildContext.protocol_content); wer Blöcke ändert, verwirft ihn (forget_protocol_content)."""

    def __init__(self, db: Session, protocol: Protocol):
        self.db = db
        self.protocol = protocol
        self.elements = list_protocol_elements(db, protocol.id)
        self._blocks: dict[int, list[ProtocolElementBlock]] = {element.id: [] for element in self.elements}
        if self._blocks:
            for block in db.scalars(
                select(ProtocolElementBlock)
                .where(ProtocolElementBlock.protocol_element_id.in_(list(self._blocks)))
                .order_by(ProtocolElementBlock.sort_index.asc(), ProtocolElementBlock.id.asc())
            ):
                self._blocks[block.protocol_element_id].append(block)
        self._block_ids = {block.id for blocks in self._blocks.values() for block in blocks}
        self._texts: dict[int, ProtocolText] | None = None
        self._images: dict[int, list] | None = None
        self._todos: list | None = None

    def blocks(self, element_id: int) -> list[ProtocolElementBlock]:
        if element_id not in self._blocks:
            return list_element_blocks(self.db, element_id)
        return list(self._blocks[element_id])

    def _known(self, block_id: int | None) -> bool:
        return block_id is not None and block_id in self._block_ids

    def text(self, block_id: int | None) -> ProtocolText | None:
        if block_id is None:
            return None
        if not self._known(block_id):
            return get_protocol_text(self.db, block_id)
        if self._texts is None:
            self._texts = {
                text.protocol_element_block_id: text
                for text in self.db.scalars(select(ProtocolText).where(ProtocolText.protocol_element_block_id.in_(self._block_ids)))
            }
        return self._texts.get(block_id)

    def images(self, block_id: int | None) -> list:
        if block_id is None:
            return []
        if not self._known(block_id):
            return list_protocol_images(self.db, block_id)
        if self._images is None:
            self._images = {}
            for row in self.db.execute(
                select(ProtocolImage, StoredFile)
                .join(StoredFile, StoredFile.id == ProtocolImage.stored_file_id)
                .where(ProtocolImage.protocol_element_block_id.in_(self._block_ids))
                .order_by(ProtocolImage.sort_index.asc(), ProtocolImage.id.asc())
            ).all():
                self._images.setdefault(row.ProtocolImage.protocol_element_block_id, []).append(row)
        return list(self._images.get(block_id, []))

    def _live_todos(self) -> list:
        if self._todos is None:
            self._todos = self.db.execute(
                _todo_query().where(Protocol.id == self.protocol.id).order_by(ProtocolTodo.sort_index.asc(), ProtocolTodo.id.asc())
            ).all()
        return self._todos

    def block_todos(self, block_id: int | None) -> list:
        if block_id is None:
            return []
        if _frozen_todo_snapshot(self.protocol) is not None or not self._known(block_id):
            return list(list_block_todos(self.db, self.protocol, block_id))
        return [row for row in self._live_todos() if row.ProtocolTodo.protocol_element_block_id == block_id]

    def todos_by_tag(self, tag: str) -> list:
        if _frozen_todo_snapshot(self.protocol) is not None:
            return list(list_todos_by_tag(self.db, self.protocol, tag))
        # wie ProtocolTodo.tags @> [tag]: exakt dieses Element der Liste
        return [row for row in self._live_todos() if tag in (row.ProtocolTodo.tags or [])]
