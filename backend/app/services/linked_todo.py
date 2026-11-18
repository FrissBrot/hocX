"""Pendenz eines «Pro Pendenz»-Blocks (repeat_source_type «todo») für die Zeilen «aus der Pendenz»
im Tabellenblock: im Protokoll-Editor (ProtocolElementBlockRead.linked_todo) und im PDF. Die Werte
sind live (wie die Terminfelder), aber nur lesend - bearbeitet wird die Pendenz selbst.

Geladen wird nur aus dem eigenen Mandanten (ProtocolTodo.tenant_id, Migration 0131); eine fremde
oder gelöschte Pendenz ergibt None, die Zeilen fallen dann weg."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Participant, Protocol, ProtocolElement, ProtocolElementBlock, ProtocolTodo
from app.models.entities import TodoStatus

# Reihenfolge im Editor und im PDF
TODO_FIELDS = ("task", "description", "participant", "due_date", "status", "origin")


@dataclass(frozen=True)
class LinkedTodo:
    task: str
    description: str | None
    participant: str | None
    due_date: date | None
    due_marker: str | None
    status_code: str | None
    protocol_number: str | None
    block_title: str | None

    @property
    def origin(self) -> str:
        return " · ".join(part for part in (self.protocol_number, self.block_title) if part)


def linked_todo_id(config: dict | None) -> int | None:
    config = config or {}
    if config.get("repeat_source_type") != "todo" or not str(config.get("repeat_source_id") or "").isdigit():
        return None
    return int(config["repeat_source_id"])


def load_linked_todo(db: Session, config: dict | None, tenant_id: int | None) -> LinkedTodo | None:
    todo_id = linked_todo_id(config)
    if todo_id is None or tenant_id is None:
        return None
    row = db.execute(
        select(
            ProtocolTodo,
            TodoStatus.code,
            Participant.display_name,
            Protocol.protocol_number,
            ProtocolElementBlock.block_title_snapshot,
        )
        .join(TodoStatus, TodoStatus.id == ProtocolTodo.todo_status_id)
        .outerjoin(Participant, (Participant.id == ProtocolTodo.assigned_participant_id) & (Participant.tenant_id == tenant_id))
        .outerjoin(ProtocolElementBlock, ProtocolElementBlock.id == ProtocolTodo.protocol_element_block_id)
        .outerjoin(ProtocolElement, ProtocolElement.id == ProtocolElementBlock.protocol_element_id)
        .outerjoin(Protocol, (Protocol.id == ProtocolElement.protocol_id) & (Protocol.tenant_id == tenant_id))
        .where(ProtocolTodo.id == todo_id, ProtocolTodo.tenant_id == tenant_id)
    ).first()
    if row is None:
        return None
    todo, status_code, participant_name, protocol_number, block_title = row
    return LinkedTodo(
        task=todo.task,
        description=todo.reference_link,
        participant=participant_name,
        due_date=todo.due_date,
        due_marker=todo.due_marker,
        status_code=status_code,
        protocol_number=protocol_number,
        block_title=block_title,
    )
