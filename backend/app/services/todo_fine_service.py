"""Bussen für zu spät erledigte Pendenzen (Migration 0169).

Ablauf
------
- Solange ein Todo offen ist und seine Fälligkeit vorbei ist, läuft die Busse: sie wird bei jeder
  Abfrage neu gerechnet (nicht gespeichert) und wächst mit jedem vollen Intervall.
- Wird das Todo erledigt ("done"), friert ``sync_todo`` den Betrag je verantwortliche Person als
  ``todo_fine`` (status pending) ein. Erst diese Zeilen können einkassiert oder erlassen werden.
- Wird das Todo wieder geöffnet, verschwinden die noch offenen eingefrorenen Bussen; einkassierte
  oder erlassene bleiben stehen. "Abgebrochen" (cancelled) ist keine Verspätung.

Welche Busse gilt
-----------------
``fine_mode`` am Todo: ``none`` keine Busse, ``fixed`` fixer Betrag, ``rule`` eine bestimmte
Regel, ``auto`` (Standard) die passende Regel. Passen im Modus ``auto`` mehrere Regeln, entsteht
keine Busse, sondern ein Konflikt, den jemand mit finances.manage am Todo von Hand auflöst.

Eine Regel passt, wenn sie aktiv ist, die Fälligkeit ab ``applies_from`` liegt und jede gesetzte
Filterart passt (Tags, Aufgabenpaket, Verantwortliche, Rollen der Verantwortlichen; innerhalb einer
Art genügt ein Treffer, eine leere Art schränkt nicht ein).

Betrag je Person (Tarif der Person, sonst Standardtarif):
    Grundbetrag + floor(Tage zu spät / Intervall) x Intervallbetrag
Beispiel Intervall 2 Tage, 5.- Grundbetrag, 2.- pro Intervall: 1 Tag zu spät 5.-, 2 Tage 7.-,
5 Tage 9.-. Bei Aufteilung ("split") zahlt jede Person ihren Betrag geteilt durch die Zahl der
Verantwortlichen.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import (
    FinanceAccount,
    FinanceTransaction,
    FineTariff,
    FineTariffGroup,
    Participant,
    ProtocolTodo,
    ProtocolTodoAssignee,
    TaskPackageItem,
    TodoFine,
    TodoFineRule,
    TodoFineRuleParticipant,
    TodoFineRuleRate,
    TodoFineRuleRole,
    TodoFineRuleTaskPackage,
    TodoStatus,
)
from app.core.features_generated import F
from app.models.entities import TenantFeature, UserRole

TZ = ZoneInfo("Europe/Zurich")
CENTS = Decimal("0.01")
OPEN_STATUS_CODES = ("open", "in_progress")


def module_active(db: Session, tenant_id: int) -> bool:
    """Eigenes Feature `todo_fines`: nur voll gebucht entstehen neue Bussen. Im Nur-Lesen-Zustand
    (abgeschaltet) bleiben bestehende Bussen stehen, es wird nichts mehr eingefroren."""
    return db.scalar(
        select(TenantFeature.id).where(
            TenantFeature.tenant_id == tenant_id, TenantFeature.feature_code == F.TODO_FINES, TenantFeature.access == "full"
        ).limit(1)
    ) is not None


def today() -> date:
    return datetime.now(TZ).date()


def local_date(value: datetime) -> date:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(TZ).date()


def money(value: Decimal | float | int) -> Decimal:
    return Decimal(str(value)).quantize(CENTS, rounding=ROUND_HALF_UP)


def rule_amount(base: Decimal, per_interval: Decimal, interval_days: int, days_late: int) -> Decimal:
    """Betrag einer Regel für `days_late` (>= 1) Tage Verspätung."""
    if days_late < 1:
        return Decimal("0")
    return money(Decimal(base) + Decimal(days_late // max(interval_days, 1)) * Decimal(per_interval))


# ── Geladene Daten ───────────────────────────────────────────────────


@dataclass
class RuleData:
    id: int
    public_id: object
    name: str
    applies_from: date
    interval_days: int
    split_mode: str
    account_id: int | None
    is_active: bool
    tags: set[str] = field(default_factory=set)
    task_package_ids: set[int] = field(default_factory=set)
    participant_ids: set[int] = field(default_factory=set)
    role_ids: set[int] = field(default_factory=set)
    rates: dict[int, tuple[Decimal, Decimal]] = field(default_factory=dict)


@dataclass
class PersonData:
    id: int
    public_id: object
    name: str
    tariff_group_id: int | None
    role_ids: set[int]


@dataclass
class TodoFacts:
    id: int
    public_id: object
    tenant_id: int
    task: str
    status_code: str
    due: date | None
    completed_on: date | None
    tags: list[str]
    task_package_id: int | None
    assignee_ids: list[int]
    fine_mode: str
    fine_rule_id: int | None
    fine_fixed_amount: Decimal | None
    fine_split_mode: str | None


@dataclass
class Line:
    participant_id: int
    name: str
    tariff_name: str | None
    amount: Decimal


@dataclass
class Evaluation:
    state: str
    due: date | None = None
    days_late: int = 0
    rule: RuleData | None = None
    matching: list[RuleData] = field(default_factory=list)
    split_mode: str | None = None
    account_id: int | None = None
    lines: list[Line] = field(default_factory=list)

    @property
    def total(self) -> Decimal:
        return money(sum((line.amount for line in self.lines), Decimal("0")))


class TenantFineContext:
    """Regeln, Tarife und Personen eines Mandanten - einmal laden, für viele Todos nutzen."""

    def __init__(self, db: Session, tenant_id: int) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.groups: dict[int, FineTariffGroup] = {
            group.id: group
            for group in db.scalars(
                select(FineTariffGroup).where(FineTariffGroup.tenant_id == tenant_id).order_by(FineTariffGroup.sort_index, FineTariffGroup.id)
            )
        }
        default = next((g for g in self.groups.values() if g.is_default), None) or next(iter(self.groups.values()), None)
        self.default_group_id: int | None = default.id if default else None
        tariff = db.get(FineTariff, tenant_id)
        self.fallback_account_id: int | None = tariff.account_id if tariff else None
        self.rules: list[RuleData] = self._load_rules()
        self.rules_by_id = {rule.id: rule for rule in self.rules}
        self._people: dict[int, PersonData] = {}

    def _load_rules(self) -> list[RuleData]:
        rows = self.db.scalars(
            select(TodoFineRule).where(TodoFineRule.tenant_id == self.tenant_id).order_by(TodoFineRule.sort_index, TodoFineRule.id)
        ).all()
        rules = {
            row.id: RuleData(
                id=row.id, public_id=row.public_id, name=row.name, applies_from=row.applies_from,
                interval_days=row.interval_days, split_mode=row.split_mode, account_id=row.account_id,
                is_active=row.is_active, tags={str(tag).strip().lower() for tag in (row.filter_tags or []) if str(tag).strip()},
            )
            for row in rows
        }
        if not rules:
            return []
        ids = list(rules)
        for rule_id, package_id in self.db.execute(
            select(TodoFineRuleTaskPackage.rule_id, TodoFineRuleTaskPackage.task_package_id).where(TodoFineRuleTaskPackage.rule_id.in_(ids))
        ):
            rules[rule_id].task_package_ids.add(package_id)
        for rule_id, participant_id in self.db.execute(
            select(TodoFineRuleParticipant.rule_id, TodoFineRuleParticipant.participant_id).where(TodoFineRuleParticipant.rule_id.in_(ids))
        ):
            rules[rule_id].participant_ids.add(participant_id)
        for rule_id, role_id in self.db.execute(
            select(TodoFineRuleRole.rule_id, TodoFineRuleRole.role_id).where(TodoFineRuleRole.rule_id.in_(ids))
        ):
            rules[rule_id].role_ids.add(role_id)
        for rate in self.db.scalars(select(TodoFineRuleRate).where(TodoFineRuleRate.rule_id.in_(ids))):
            rules[rate.rule_id].rates[rate.tariff_group_id] = (Decimal(rate.base_amount), Decimal(rate.interval_amount))
        return list(rules.values())

    def people(self, ids: list[int]) -> dict[int, PersonData]:
        missing = [pid for pid in set(ids) if pid not in self._people]
        if missing:
            roles: dict[int, set[int]] = defaultdict(set)
            for user_id, role_id in self.db.execute(
                select(UserRole.user_id, UserRole.role_id).where(UserRole.tenant_id == self.tenant_id, UserRole.user_id.in_(missing))
            ):
                roles[user_id].add(role_id)
            for person in self.db.execute(
                select(Participant.id, Participant.public_id, Participant.display_name, Participant.fine_tariff_group_id).where(
                    Participant.id.in_(missing), Participant.tenant_id == self.tenant_id
                )
            ):
                self._people[person.id] = PersonData(person.id, person.public_id, person.display_name, person.fine_tariff_group_id, roles[person.id])
        return {pid: self._people[pid] for pid in ids if pid in self._people}

    def group_for(self, person: PersonData) -> int | None:
        if person.tariff_group_id in self.groups:
            return person.tariff_group_id
        return self.default_group_id

    def group_name(self, group_id: int | None) -> str | None:
        group = self.groups.get(group_id) if group_id is not None else None
        return group.name if group else None

    def account_for(self, rule: RuleData | None) -> int | None:
        return (rule.account_id if rule else None) or self.fallback_account_id


# ── Todos laden ──────────────────────────────────────────────────────


def _facts_query(tenant_id: int):
    from app.repositories.protocol_todo_repository import ProtocolTodoRepository

    query, *_ = ProtocolTodoRepository()._base_todo_query()
    return query.add_columns(TaskPackageItem.task_package_id.label("task_package_internal_id")).where(
        ProtocolTodo.tenant_id == tenant_id, ProtocolTodo.pending_delete.is_(False)
    )


def _facts_from_row(row) -> TodoFacts:
    todo: ProtocolTodo = row[0]
    assignees = list(row.assignee_ids or []) or ([todo.assigned_participant_id] if todo.assigned_participant_id else [])
    return TodoFacts(
        id=todo.id, public_id=todo.public_id, tenant_id=todo.tenant_id, task=todo.task, status_code=row.todo_status_code,
        due=row.resolved_due_date, completed_on=local_date(todo.completed_at) if todo.completed_at else None,
        tags=[str(tag) for tag in (todo.tags or [])], task_package_id=row.task_package_internal_id, assignee_ids=assignees,
        fine_mode=todo.fine_mode or "auto", fine_rule_id=todo.fine_rule_id,
        fine_fixed_amount=Decimal(todo.fine_fixed_amount) if todo.fine_fixed_amount is not None else None,
        fine_split_mode=todo.fine_split_mode,
    )


def load_facts(db: Session, todo: ProtocolTodo) -> TodoFacts | None:
    row = db.execute(_facts_query(todo.tenant_id).where(ProtocolTodo.id == todo.id)).first()
    return _facts_from_row(row) if row else None


# ── Auswertung ───────────────────────────────────────────────────────


def rule_matches(ctx: TenantFineContext, rule: RuleData, facts: TodoFacts) -> bool:
    if not rule.is_active or facts.due is None or facts.due < rule.applies_from:
        return False
    if rule.tags and not rule.tags & {tag.strip().lower() for tag in facts.tags}:
        return False
    if rule.task_package_ids and facts.task_package_id not in rule.task_package_ids:
        return False
    if rule.participant_ids and not rule.participant_ids & set(facts.assignee_ids):
        return False
    if rule.role_ids:
        people = ctx.people(facts.assignee_ids)
        if not any(rule.role_ids & person.role_ids for person in people.values()):
            return False
    return True


def matching_rules(ctx: TenantFineContext, facts: TodoFacts) -> list[RuleData]:
    return [rule for rule in ctx.rules if rule_matches(ctx, rule, facts)]


def evaluate(ctx: TenantFineContext, facts: TodoFacts, *, on: date | None = None) -> Evaluation:
    """Busse eines Todos am Stichtag: erledigt -> Erledigungsdatum, offen -> `on` (heute)."""
    if facts.fine_mode == "none":
        return Evaluation(state="none", due=facts.due)
    if facts.status_code == "cancelled":
        return Evaluation(state="cancelled", due=facts.due)
    if facts.due is None:
        return Evaluation(state="no_due_date")
    reference = facts.completed_on if facts.status_code == "done" and facts.completed_on else (on or today())
    days_late = (reference - facts.due).days
    if days_late < 1:
        return Evaluation(state="on_time", due=facts.due)

    matching = matching_rules(ctx, facts) if facts.fine_mode == "auto" else []
    rule: RuleData | None = None
    if facts.fine_mode == "fixed":
        pass
    elif facts.fine_mode == "rule":
        rule = ctx.rules_by_id.get(facts.fine_rule_id) if facts.fine_rule_id else None
        if rule is None:
            return Evaluation(state="rule_missing", due=facts.due, days_late=days_late)
    elif len(matching) > 1:
        return Evaluation(state="conflict", due=facts.due, days_late=days_late, matching=matching)
    elif not matching:
        return Evaluation(state="no_rule", due=facts.due, days_late=days_late)
    else:
        rule = matching[0]

    if not facts.assignee_ids:
        return Evaluation(state="no_assignee", due=facts.due, days_late=days_late, rule=rule, matching=matching)
    people = ctx.people(facts.assignee_ids)
    split_mode = (facts.fine_split_mode or "each") if rule is None else rule.split_mode
    share = Decimal(len(people)) if split_mode == "split" and people else Decimal(1)
    lines: list[Line] = []
    for person in (people[pid] for pid in facts.assignee_ids if pid in people):
        group_id = ctx.group_for(person)
        if rule is None:
            full = money(facts.fine_fixed_amount or 0)
            tariff_name = None
        else:
            base, per_interval = rule.rates.get(group_id, (Decimal("0"), Decimal("0"))) if group_id is not None else (Decimal("0"), Decimal("0"))
            full = rule_amount(base, per_interval, rule.interval_days, days_late)
            tariff_name = ctx.group_name(group_id)
        lines.append(Line(person.id, person.name, tariff_name, money(full / share)))
    return Evaluation(
        state="ok", due=facts.due, days_late=days_late, rule=rule, matching=matching, split_mode=split_mode,
        account_id=ctx.account_for(rule), lines=lines,
    )


# ── Einfrieren beim Erledigen ────────────────────────────────────────


def sync_todo(db: Session, todo: ProtocolTodo, *, ctx: TenantFineContext | None = None) -> None:
    """Hält die eingefrorenen Bussen eines Todos aktuell (ohne Commit).

    Nicht erledigt: offene eingefrorene Bussen löschen. Erledigt: offene eingefrorene Bussen neu
    rechnen; einkassierte oder erlassene bleiben, und für ihre Person entsteht keine neue."""
    if not module_active(db, todo.tenant_id):
        return
    facts = load_facts(db, todo)
    if facts is None:
        return
    db.execute(delete(TodoFine).where(TodoFine.protocol_todo_id == todo.id, TodoFine.status == "pending"))
    if facts.status_code != "done" or facts.completed_on is None:
        return
    ctx = ctx or TenantFineContext(db, facts.tenant_id)
    evaluation = evaluate(ctx, facts)
    if evaluation.state != "ok":
        return
    settled = set(db.scalars(select(TodoFine.participant_id).where(TodoFine.protocol_todo_id == todo.id)))
    for line in evaluation.lines:
        if line.participant_id in settled or line.amount <= 0:
            continue
        db.add(TodoFine(
            tenant_id=facts.tenant_id, protocol_todo_id=facts.id, rule_id=evaluation.rule.id if evaluation.rule else None,
            participant_id=line.participant_id, participant_name_snapshot=line.name, task_snapshot=facts.task,
            rule_name_snapshot=evaluation.rule.name if evaluation.rule else None, tariff_name_snapshot=line.tariff_name,
            due_date=facts.due, completed_on=facts.completed_on, days_late=evaluation.days_late, amount=line.amount,
            account_id=evaluation.account_id, status="pending",
        ))
    db.flush()


# ── Liste ────────────────────────────────────────────────────────────


@dataclass
class OpenItem:
    """Laufende Busse (Todo offen) oder Konflikt (offen oder erledigt, ohne eingefrorene Busse)."""

    facts: TodoFacts
    evaluation: Evaluation


def open_items(db: Session, tenant_id: int, *, participant_id: int | None = None, on: date | None = None) -> list[OpenItem]:
    """Laufende Bussen und Konflikte. Mit `participant_id` nur Todos dieser Person."""
    ctx = TenantFineContext(db, tenant_id)
    if not ctx.rules and not db.scalar(
        select(ProtocolTodo.id).where(ProtocolTodo.tenant_id == tenant_id, ProtocolTodo.fine_mode.in_(("fixed", "rule"))).limit(1)
    ):
        return []
    has_due = (ProtocolTodo.due_date.is_not(None)) | (ProtocolTodo.due_event_id.is_not(None)) | (ProtocolTodo.due_marker.is_not(None))
    earliest = min((rule.applies_from for rule in ctx.rules if rule.is_active), default=None)
    without_fines = ~select(TodoFine.id).where(TodoFine.protocol_todo_id == ProtocolTodo.id).exists()
    # Offen: laufende Busse. Erledigt ohne eingefrorene Busse: nur Konflikte (seit der frühesten Regel).
    done_scope = TodoStatus.code == "done"
    if earliest is not None:
        done_scope = done_scope & (ProtocolTodo.completed_at >= datetime.combine(earliest, datetime.min.time(), tzinfo=TZ))
    query = _facts_query(tenant_id).where(
        has_due, ProtocolTodo.fine_mode != "none",
        TodoStatus.code.in_(OPEN_STATUS_CODES) | (done_scope & without_fines),
    )
    if participant_id is not None:
        query = query.where(
            (ProtocolTodo.assigned_participant_id == participant_id)
            | select(ProtocolTodoAssignee.protocol_todo_id).where(
                ProtocolTodoAssignee.protocol_todo_id == ProtocolTodo.id, ProtocolTodoAssignee.participant_id == participant_id
            ).exists()
        )
    items: list[OpenItem] = []
    for row in db.execute(query):
        facts = _facts_from_row(row)
        evaluation = evaluate(ctx, facts, on=on)
        if facts.status_code == "done":
            if evaluation.state == "conflict":
                items.append(OpenItem(facts, evaluation))
        elif evaluation.state in ("ok", "conflict"):
            items.append(OpenItem(facts, evaluation))
    return items


# ── Einkassieren, Erlassen ───────────────────────────────────────────


class TodoFineError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _locked(db: Session, fine_id: int, tenant_id: int) -> TodoFine | None:
    return db.execute(
        select(TodoFine).where(TodoFine.id == fine_id, TodoFine.tenant_id == tenant_id).with_for_update()
    ).scalar_one_or_none()


def collect(db: Session, fine_id: int, tenant_id: int, actor_user_id: int) -> TodoFine | None:
    fine = _locked(db, fine_id, tenant_id)
    if fine is None or fine.status != "pending":
        return None
    account_id = fine.account_id
    if account_id is None:
        rule_account = db.scalar(select(TodoFineRule.account_id).where(TodoFineRule.id == fine.rule_id)) if fine.rule_id else None
        tariff = db.get(FineTariff, tenant_id)
        account_id = rule_account or (tariff.account_id if tariff else None)
    account = db.get(FinanceAccount, account_id) if account_id else None
    if account is None or account.tenant_id != tenant_id:
        raise TodoFineError("no_account", "Kein Konto für diese Busse festgelegt")
    now = datetime.now(timezone.utc)
    tx = FinanceTransaction(
        account_id=account.id, amount=fine.amount, description=f"Busse Pendenz: {fine.participant_name_snapshot} - {fine.task_snapshot}"[:500],
        transaction_date=local_date(now),
    )
    db.add(tx)
    db.flush()
    fine.account_id = account.id
    fine.status = "collected"
    fine.collected_at = now
    fine.collected_transaction_id = tx.id
    fine.collected_by_user_id = actor_user_id
    db.commit()
    return fine


def reopen(db: Session, fine_id: int, tenant_id: int) -> TodoFine | None:
    fine = _locked(db, fine_id, tenant_id)
    if fine is None or fine.status != "collected":
        return None
    if fine.collected_transaction_id:
        tx = db.get(FinanceTransaction, fine.collected_transaction_id)
        if tx is not None:
            db.delete(tx)
    fine.status = "pending"
    fine.collected_at = None
    fine.collected_transaction_id = None
    fine.collected_by_user_id = None
    db.commit()
    return fine


def waive(db: Session, fine_id: int, tenant_id: int, actor_user_id: int, reason: str) -> TodoFine | None:
    reason = reason.strip()
    if not reason:
        raise TodoFineError("reason_required", "Für das Erlassen einer Busse ist eine Begründung nötig")
    fine = _locked(db, fine_id, tenant_id)
    if fine is None or fine.status != "pending":
        return None
    fine.status = "deleted"
    fine.delete_comment = reason
    fine.deleted_at = datetime.now(timezone.utc)
    fine.deleted_by_user_id = actor_user_id
    db.commit()
    return fine


def restore(db: Session, fine_id: int, tenant_id: int) -> TodoFine | None:
    fine = _locked(db, fine_id, tenant_id)
    if fine is None or fine.status != "deleted":
        return None
    fine.status = "pending"
    fine.delete_comment = None
    fine.deleted_at = None
    fine.deleted_by_user_id = None
    db.commit()
    return fine


def todo_status_code(db: Session, todo: ProtocolTodo) -> str | None:
    return db.scalar(select(TodoStatus.code).where(TodoStatus.id == todo.todo_status_id))
