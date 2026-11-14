"""Bussen-Mails (Design «hocX E-Mails», M11 und M12).

- **Busse droht** (``fine.upcoming``): 3 Tage vor der Fälligkeit einer offenen Aufgabe, für die
  bei Verspätung eine Pendenzen-Busse anfiele (Regel oder Fixbetrag). Ersetzt für diese Person und
  Aufgabe die Erinnerung «in 3 Tagen fällig» - angelegt von ``todos.scan_reminders``. Die Staffel
  rechnet ``todo_fine_service.evaluate`` für die Tage nach der Fälligkeit vor.
- **Busse erhalten** (``fine.issued``): Anwesenheitsbussen beim Abschluss des Protokolls (vorher
  sind sie noch Entwurf), Pendenzen-Bussen beim Einfrieren nach dem Erledigen. Mehrere landen in
  einer Mail, mit der Summe aller offenen Bussen der Person.

Wie bei den Aufgaben-Mails prüft der Versand alles neu: gelöschte, kassierte oder umgebuchte
Bussen und erledigte Aufgaben fallen weg.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Iterable
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AttendanceFine, Notification, Protocol, ProtocolTodo, Tenant, TodoFine
from app.notifications import publish

TZ = ZoneInfo("Europe/Zurich")
# Staffel: höchstens so viele Stufen, gesucht über so viele Tage nach der Fälligkeit
MAX_STEPS = 3
STEP_HORIZON_DAYS = 120


def _today() -> date:
    return datetime.now(TZ).date()


def _currency(db: Session, tenant_id: int) -> str:
    return db.scalar(select(Tenant.finance_currency).where(Tenant.id == tenant_id)) or "CHF"


# ── Busse erhalten ───────────────────────────────────────────────────


def on_protocol_closed(db: Session, protocol: Protocol) -> int:
    """Offene Anwesenheitsbussen des Protokolls an die gebüssten Personen (ohne Commit)."""
    created = 0
    for fine_id, participant_id in db.execute(
        select(AttendanceFine.id, AttendanceFine.participant_id).where(
            AttendanceFine.protocol_id == protocol.id, AttendanceFine.status == "pending", AttendanceFine.participant_id.is_not(None),
        )
    ):
        created += publish(
            db, kind="fine.issued", tenant_id=protocol.tenant_id, recipient_ids=[participant_id], subject_id=fine_id,
            payload={"type": "attendance"}, dedupe=f"attendance:{fine_id}",
        )
    return created


def on_todo_fines_frozen(db: Session, fines: Iterable[TodoFine]) -> int:
    """Eben eingefrorene Pendenzen-Bussen melden (ohne Commit, nach dem Flush mit IDs)."""
    created = 0
    for fine in fines:
        if fine.participant_id is None or fine.id is None:
            continue
        created += publish(
            db, kind="fine.issued", tenant_id=fine.tenant_id, recipient_ids=[fine.participant_id], subject_id=fine.id,
            payload={"type": "todo"}, dedupe=f"todo:{fine.id}",
        )
    return created


def open_total(db: Session, tenant_id: int, participant_id: int) -> Decimal:
    """Summe aller offenen Bussen der Person im Verein (Anwesenheit und Pendenzen)."""
    attendance = db.scalar(
        select(func.coalesce(func.sum(AttendanceFine.amount), 0))
        .join(Protocol, Protocol.id == AttendanceFine.protocol_id)
        .where(Protocol.tenant_id == tenant_id, AttendanceFine.participant_id == participant_id, AttendanceFine.status == "pending")
    ) or 0
    todo = db.scalar(
        select(func.coalesce(func.sum(TodoFine.amount), 0))
        .where(TodoFine.tenant_id == tenant_id, TodoFine.participant_id == participant_id, TodoFine.status == "pending")
    ) or 0
    return Decimal(str(attendance)) + Decimal(str(todo))


def _local_date(value: datetime | None) -> date:
    return value.astimezone(TZ).date() if value else _today()


def issued_items_for(db: Session, notifications: list[Notification], recipient_id: int, **_) -> dict[int, dict]:
    if not notifications:
        return {}
    tenant_id = notifications[0].tenant_id
    attendance_ids = [n.subject_id for n in notifications if (n.payload or {}).get("type") == "attendance" and n.subject_id]
    todo_ids = [n.subject_id for n in notifications if (n.payload or {}).get("type") == "todo" and n.subject_id]
    attendance = {
        row.AttendanceFine.id: row
        for row in db.execute(
            select(AttendanceFine, Protocol.title, Protocol.protocol_date, Protocol.protocol_number, Protocol.tenant_id.label("tenant_id"))
            .join(Protocol, Protocol.id == AttendanceFine.protocol_id)
            .where(AttendanceFine.id.in_(attendance_ids), Protocol.tenant_id == tenant_id)
        )
    } if attendance_ids else {}
    todo_fines = {
        fine.id: fine for fine in db.scalars(select(TodoFine).where(TodoFine.id.in_(todo_ids), TodoFine.tenant_id == tenant_id))
    } if todo_ids else {}
    currency = _currency(db, tenant_id)
    items: dict[int, dict] = {}
    for notification in notifications:
        kind = (notification.payload or {}).get("type")
        if kind == "attendance":
            row = attendance.get(notification.subject_id)
            fine = row.AttendanceFine if row else None
            if fine is None or fine.status != "pending" or fine.participant_id != recipient_id:
                continue
            items[notification.id] = {
                "type": "attendance", "fine_type": fine.fine_type, "amount": Decimal(str(fine.amount)), "currency": currency,
                "protocol_title": row.title or "", "protocol_date": row.protocol_date, "protocol_number": row.protocol_number or "",
                "issued_on": _local_date(notification.created_at),
            }
        elif kind == "todo":
            fine = todo_fines.get(notification.subject_id)
            if fine is None or fine.status != "pending" or fine.participant_id != recipient_id:
                continue
            items[notification.id] = {
                "type": "todo", "task": fine.task_snapshot or "", "due": fine.due_date, "rule_name": fine.rule_name_snapshot,
                "tariff_name": fine.tariff_name_snapshot, "amount": Decimal(str(fine.amount)), "currency": currency,
                "issued_on": _local_date(notification.created_at),
            }
    if items:
        total = open_total(db, tenant_id, recipient_id)
        for item in items.values():
            item["open_total"] = total
    return items


# ── Busse droht ──────────────────────────────────────────────────────


class UpcomingCalculator:
    """Rechnet je Mandant einmal den Kontext (Regeln, Tarife) und daraus die Staffel je Person."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self._contexts: dict[int, object] = {}
        self._active: dict[int, bool] = {}

    def _context(self, tenant_id: int):
        from app.services import todo_fine_service as fine_service

        if tenant_id not in self._contexts:
            self._contexts[tenant_id] = fine_service.TenantFineContext(self.db, tenant_id)
        return self._contexts[tenant_id]

    def module_active(self, tenant_id: int) -> bool:
        from app.services import todo_fine_service as fine_service

        if tenant_id not in self._active:
            self._active[tenant_id] = fine_service.module_active(self.db, tenant_id)
        return self._active[tenant_id]

    def steps(self, todo: ProtocolTodo, recipient_id: int) -> tuple[list[tuple[date, Decimal]], object | None, object | None]:
        """Staffel ``[(ab Datum, Betrag)]`` für die Person, dazu Fakten und Auswertung; leer, wenn
        bei Verspätung keine Busse anfiele."""
        from app.services import todo_fine_service as fine_service

        if not self.module_active(todo.tenant_id):
            return [], None, None
        facts = fine_service.load_facts(self.db, todo)
        if facts is None or facts.due is None or facts.fine_mode == "none" or facts.status_code not in fine_service.OPEN_STATUS_CODES:
            return [], facts, None
        ctx = self._context(todo.tenant_id)
        steps: list[tuple[date, Decimal]] = []
        first = None
        last: Decimal | None = None
        for day in range(1, STEP_HORIZON_DAYS + 1):
            evaluation = fine_service.evaluate(ctx, facts, on=facts.due + timedelta(days=day))
            if evaluation.state != "ok":
                if day == 1:
                    return [], facts, evaluation
                continue
            first = first or evaluation
            amount = next((line.amount for line in evaluation.lines if line.participant_id == recipient_id), None)
            if amount is None or amount <= 0:
                if day == 1:
                    return [], facts, evaluation
                continue
            if last is None or amount != last:
                steps.append((facts.due + timedelta(days=day), amount))
                last = amount
                if len(steps) >= MAX_STEPS:
                    break
            # Fixbetrag ändert sich nie
            if evaluation.rule is None:
                break
        return steps, facts, first


def upcoming_items_for(db: Session, notifications: list[Notification], recipient_id: int, **_) -> dict[int, dict]:
    from app.repositories.protocol_todo_repository import ProtocolTodoRepository

    todo_ids = {n.subject_id for n in notifications if n.subject_id}
    if not todo_ids:
        return {}
    query, *_ = ProtocolTodoRepository()._base_todo_query()
    rows = {row[0].id: row for row in db.execute(query.where(ProtocolTodo.id.in_(todo_ids)))}
    calculator = UpcomingCalculator(db)
    today = _today()
    items: dict[int, dict] = {}
    for notification in notifications:
        row = rows.get(notification.subject_id)
        if row is None:
            continue
        todo: ProtocolTodo = row[0]
        due = row.resolved_due_date
        if todo.tenant_id != notification.tenant_id or todo.pending_delete or due is None or due.isoformat() != notification.payload.get("due"):
            continue
        if due < today:
            continue
        steps, facts, evaluation = calculator.steps(todo, recipient_id)
        if not steps or facts is None or recipient_id not in facts.assignee_ids:
            continue
        rule = getattr(evaluation, "rule", None)
        items[notification.id] = {
            "task": todo.task, "due": due, "days_left": max((due - today).days, 0), "steps": steps,
            "currency": _currency(db, todo.tenant_id), "rule_name": rule.name if rule else None, "fixed": rule is None,
            "source": row.task_package_name or (row.protocol_number if row.protocol_id else None),
        }
    return items
