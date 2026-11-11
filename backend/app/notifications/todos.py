"""Benachrichtigungen zu Aufgaben (Todos).

Wann eine Aufgabe «freigegeben» ist und gemeldet wird (Vorgabe 2026-11-11):
- Aufgaben ohne Protokoll (auch aus Aufgabenpaketen und der Abgabebox): beim Erstellen bzw. wenn
  jemand neu verantwortlich wird.
- Aufgaben aus einem Protokoll: erst wenn das Protokoll abgeschlossen wird, dann alle offenen auf
  einmal. Danach (Aufgaben bleiben bearbeitbar) wie Aufgaben ohne Protokoll.

Erinnerungen (Loop todo_reminders, einmal täglich ab 07:00): «fällig in 3 Tagen» und «seit gestern
überfällig», je Aufgabe, Person und Fälligkeit nur einmal (dedupe). Wer sich selbst eine Aufgabe
gibt, bekommt dafür keine Mail.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Iterable
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Protocol, ProtocolElement, ProtocolElementBlock, ProtocolTodo, ProtocolTodoAssignee, TodoStatus
from app.notifications import publish
from app.notifications.catalog import DUE_SOON_DAYS

TZ = ZoneInfo("Europe/Zurich")
OPEN_STATUS_CODES = ("open", "in_progress")
REMINDER_HOUR = 7


def _protocol_status(db: Session, todo: ProtocolTodo) -> str | None:
    if todo.protocol_element_block_id is None:
        return None
    return db.scalar(
        select(Protocol.status)
        .join(ProtocolElement, ProtocolElement.protocol_id == Protocol.id)
        .join(ProtocolElementBlock, ProtocolElementBlock.protocol_element_id == ProtocolElement.id)
        .where(ProtocolElementBlock.id == todo.protocol_element_block_id)
    )


def released(db: Session, todo: ProtocolTodo) -> bool:
    """Ohne Protokoll immer, sonst erst ab «abgeschlossen»."""
    return todo.protocol_element_block_id is None or _protocol_status(db, todo) == "abgeschlossen"


def assignee_ids(db: Session, todo: ProtocolTodo) -> list[int]:
    ids = list(
        db.scalars(
            select(ProtocolTodoAssignee.participant_id)
            .where(ProtocolTodoAssignee.protocol_todo_id == todo.id)
            .order_by(ProtocolTodoAssignee.sort_index)
        )
    )
    return ids or ([todo.assigned_participant_id] if todo.assigned_participant_id else [])


def _is_open(db: Session, todo: ProtocolTodo) -> bool:
    return db.scalar(select(TodoStatus.code).where(TodoStatus.id == todo.todo_status_id)) in OPEN_STATUS_CODES


def on_assignees_added(db: Session, todo: ProtocolTodo, participant_ids: Iterable[int], *, actor_user_id: int | None = None) -> int:
    """Neue Verantwortliche einer Aufgabe melden - nur wenn die Aufgabe freigegeben und offen ist."""
    recipients = [pid for pid in participant_ids if pid is not None and pid != actor_user_id]
    if not recipients or todo.pending_delete or not _is_open(db, todo) or not released(db, todo):
        return 0
    return publish(db, kind="todo.assigned", tenant_id=todo.tenant_id, recipient_ids=recipients, subject_id=todo.id, dedupe=str(todo.id))


def on_protocol_closed(db: Session, protocol_id: int, *, actor_user_id: int | None = None) -> int:
    """Alle offenen Aufgaben des Protokolls an ihre Verantwortlichen melden (eine Sammelmail je Person)."""
    todos = db.scalars(
        select(ProtocolTodo)
        .join(ProtocolElementBlock, ProtocolElementBlock.id == ProtocolTodo.protocol_element_block_id)
        .join(ProtocolElement, ProtocolElement.id == ProtocolElementBlock.protocol_element_id)
        .join(TodoStatus, TodoStatus.id == ProtocolTodo.todo_status_id)
        .where(ProtocolElement.protocol_id == protocol_id, TodoStatus.code.in_(OPEN_STATUS_CODES), ProtocolTodo.pending_delete.is_(False))
    ).all()
    created = 0
    for todo in todos:
        recipients = [pid for pid in assignee_ids(db, todo) if pid != actor_user_id]
        if recipients:
            created += publish(db, kind="todo.assigned", tenant_id=todo.tenant_id, recipient_ids=recipients, subject_id=todo.id, dedupe=str(todo.id))
    return created


def now_local() -> datetime:
    return datetime.now(TZ)


def scan_reminders(db: Session, *, now: datetime | None = None) -> dict[str, int]:
    """Loop todo_reminders: Erinnerungen für heute anlegen (ab 07:00 Ortszeit, idempotent)."""
    from app.repositories.protocol_todo_repository import ProtocolTodoRepository

    now = now or now_local()
    if now.timetz().replace(tzinfo=None) < time(REMINDER_HOUR):
        return {"due_soon": 0, "overdue": 0}
    today = now.date()
    due_soon, overdue = today + timedelta(days=DUE_SOON_DAYS), today - timedelta(days=1)
    query, *_ = ProtocolTodoRepository()._base_todo_query()
    query = query.where(
        ProtocolTodo.pending_delete.is_(False),
        TodoStatus.code.in_(OPEN_STATUS_CODES),
        ProtocolTodo.due_date.in_((due_soon, overdue)) | ProtocolTodo.due_event_id.is_not(None) | ProtocolTodo.due_marker.is_not(None),
        ProtocolTodo.protocol_element_block_id.is_(None) | (Protocol.status == "abgeschlossen"),
    )
    counts = {"due_soon": 0, "overdue": 0}
    for row in db.execute(query):
        todo: ProtocolTodo = row[0]
        due: date | None = row.resolved_due_date
        kind = "todo.due_soon" if due == due_soon else "todo.overdue" if due == overdue else None
        if kind is None:
            continue
        recipients = list(row.assignee_ids or []) or ([todo.assigned_participant_id] if todo.assigned_participant_id else [])
        counts[kind.split(".")[1]] += publish(
            db, kind=kind, tenant_id=todo.tenant_id, recipient_ids=recipients, subject_id=todo.id,
            payload={"due": due.isoformat()}, dedupe=f"{todo.id}:{due.isoformat()}",
        )
    db.commit()
    return counts


# ── Beim Versand ─────────────────────────────────────────────────────


def items_for(db: Session, notifications: list, recipient_id: int) -> dict[int, dict]:
    """Aktuelle Daten der Aufgaben je Benachrichtigung. Fehlt eine Benachrichtigung im Ergebnis,
    ist sie überholt (gelöscht, erledigt, nicht mehr verantwortlich, Fälligkeit geändert)."""
    from app.repositories.protocol_todo_repository import ProtocolTodoRepository

    todo_ids = {n.subject_id for n in notifications if n.subject_id}
    if not todo_ids:
        return {}
    query, *_ = ProtocolTodoRepository()._base_todo_query()
    rows = {row[0].id: row for row in db.execute(query.where(ProtocolTodo.id.in_(todo_ids)))}
    items: dict[int, dict] = {}
    for notification in notifications:
        row = rows.get(notification.subject_id)
        if row is None:
            continue
        todo: ProtocolTodo = row[0]
        assignees = list(row.assignee_ids or []) or ([todo.assigned_participant_id] if todo.assigned_participant_id else [])
        if (
            todo.tenant_id != notification.tenant_id or todo.pending_delete or row.todo_status_code not in OPEN_STATUS_CODES
            or recipient_id not in assignees
        ):
            continue
        due = row.resolved_due_date
        if notification.kind != "todo.assigned" and (due is None or due.isoformat() != notification.payload.get("due")):
            continue
        items[notification.id] = {
            "kind": notification.kind,
            "task": todo.task,
            "due": due,
            "source": row.task_package_name or (row.protocol_number if row.protocol_id else None),
        }
    return items
