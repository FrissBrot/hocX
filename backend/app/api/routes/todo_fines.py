"""Pendenzen-Bussen: Tarife, Regeln, Bussenliste und Busse am Todo (app/services/todo_fine_service.py).

Eigenes Feature `todo_fines` (permissions/features.json): ohne Buchung 403, im Nur-Lesen-Zustand
nur die GET-Routen. Einkassieren bucht auf ein Finanzkonto und verlangt zusätzlich `finance`.

Rechte: Einstellungen lesen mit finances.read, ändern, einkassieren und erlassen mit
finances.manage. Der Tarif je Person ist eine Personenangabe (z. B. Lernende) und nur mit
finances.manage sichtbar. Die Bussenliste zeigt ohne reports.personal nur die eigenen Bussen
(wie GET /fines).
"""
from __future__ import annotations

import dataclasses
import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, aliased

from app.core.db import get_db
from app.core.features_generated import F
from app.core.permissions import P
from app.core.security import CurrentUser, get_current_user, require_feature, require_permission
from app.models import FinanceAccount, Participant, ProtocolTodo, Tenant, TodoFine, TodoFineRule
from app.schemas.todo_fines import (
    FineTariffAssignment,
    FineTariffGroupOrder,
    FineTariffGroupRead,
    FineTariffGroupWrite,
    FineTariffMember,
    TodoFineDelete,
    TodoFineFilterOptions,
    TodoFineEvaluation,
    TodoFineLine,
    TodoFineListItem,
    TodoFineRuleOrder,
    TodoFineRuleRead,
    TodoFineRuleRef,
    TodoFineRuleWrite,
    TodoFineSettings,
)
from app.services import public_id_service, todo_fine_config_service as config
from app.services import todo_fine_service as fines
from app.services.access_service import AccessService
from app.services.audit_service import AuditService

router = APIRouter()
access_service = AccessService()
audit = AuditService()
LIST_LIMIT = 1000


def _tenant(user: CurrentUser) -> int:
    if user.current_tenant_id is None:
        raise HTTPException(status_code=400, detail="No active tenant")
    return user.current_tenant_id


def _read(user: CurrentUser) -> int:
    require_permission(user, P.FINANCES_READ)
    require_feature(user, F.TODO_FINES, write=False)
    return _tenant(user)


def _manage(user: CurrentUser) -> int:
    require_permission(user, P.FINANCES_MANAGE)
    require_feature(user, F.TODO_FINES)
    return _tenant(user)


def _read_tariffs(user: CurrentUser) -> int:
    """Tarife gelten auch für Anwesenheitsbussen (0172): dafür reicht das Feature finance."""
    require_permission(user, P.FINANCES_READ)
    require_feature(user, F.FINANCE, write=False)
    return _tenant(user)


def _manage_tariffs(user: CurrentUser) -> int:
    require_permission(user, P.FINANCES_MANAGE)
    require_feature(user, F.FINANCE)
    return _tenant(user)


def _bad_request(db: Session, exc: Exception, detail: str) -> HTTPException:
    db.rollback()
    return HTTPException(status_code=400, detail=str(exc) if isinstance(exc, ValueError) else detail)


# ── Tarife ───────────────────────────────────────────────────────────


@router.get("/todo-fines/tariffs", response_model=list[FineTariffGroupRead])
def list_tariffs(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    return config.list_groups(db, _read_tariffs(user))


@router.post("/todo-fines/tariffs", response_model=FineTariffGroupRead, status_code=status.HTTP_201_CREATED)
def create_tariff(payload: FineTariffGroupWrite, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    tenant_id = _manage_tariffs(user)
    try:
        group = config.create_group(db, tenant_id, payload)
    except (SQLAlchemyError, ValueError) as exc:
        raise _bad_request(db, exc, "Tariff could not be created") from exc
    audit.log(db, action="todo_fine.tariff_created", actor=user, entity_type="fine_tariff_group", entity_id=group.id, details={"name": group.name})
    return next(g for g in config.list_groups(db, tenant_id) if g.id == group.public_id)


@router.put("/todo-fines/tariffs/order", status_code=status.HTTP_204_NO_CONTENT)
def order_tariffs(payload: FineTariffGroupOrder, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    tenant_id = _manage_tariffs(user)
    try:
        config.reorder_groups(db, tenant_id, payload.ids)
    except (SQLAlchemyError, ValueError) as exc:
        raise _bad_request(db, exc, "Order could not be saved") from exc


@router.put("/todo-fines/tariffs/{tariff_id}", response_model=FineTariffGroupRead)
def update_tariff(tariff_id: uuid.UUID, payload: FineTariffGroupWrite, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    tenant_id = _manage_tariffs(user)
    group = config.get_group(db, tenant_id, tariff_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Tariff not found")
    try:
        config.update_group(db, tenant_id, group, payload)
    except (SQLAlchemyError, ValueError) as exc:
        raise _bad_request(db, exc, "Tariff could not be saved") from exc
    audit.log(db, action="todo_fine.tariff_updated", actor=user, entity_type="fine_tariff_group", entity_id=group.id, details={"name": group.name})
    return next(g for g in config.list_groups(db, tenant_id) if g.id == tariff_id)


@router.delete("/todo-fines/tariffs/{tariff_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tariff(tariff_id: uuid.UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    tenant_id = _manage_tariffs(user)
    group = config.get_group(db, tenant_id, tariff_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Tariff not found")
    group_id, name = group.id, group.name
    try:
        config.delete_group(db, tenant_id, group)
    except SQLAlchemyError as exc:
        raise _bad_request(db, exc, "Tariff could not be deleted") from exc
    audit.log(db, action="todo_fine.tariff_deleted", actor=user, entity_type="fine_tariff_group", entity_id=group_id, details={"name": name})


@router.get("/todo-fines/tariff-members", response_model=list[FineTariffMember])
def list_tariff_members(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    # Der Tarif sagt etwas über die Person aus (Lernende, Verdienst) - nur für die Kasse.
    return config.list_members(db, _manage_tariffs(user))


@router.put("/todo-fines/tariff-members/{participant_id}", response_model=FineTariffMember)
def assign_tariff(participant_id: uuid.UUID, payload: FineTariffAssignment, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    tenant_id = _manage_tariffs(user)
    try:
        member = config.assign_member(db, tenant_id, participant_id, payload.tariff_group_id)
    except (SQLAlchemyError, ValueError) as exc:
        raise _bad_request(db, exc, "Tariff could not be assigned") from exc
    if member is None:
        raise HTTPException(status_code=404, detail="Participant not found")
    return member


# ── Regeln ───────────────────────────────────────────────────────────


@router.get("/todo-fines/rules", response_model=list[TodoFineRuleRead])
def list_rules(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    return config.list_rules(db, _read(user))


@router.get("/todo-fines/filter-options", response_model=TodoFineFilterOptions)
def get_filter_options(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    """Tags, Aufgabenpakete, Rollen und Personen für den Regelfilter (nur Namen)."""
    return config.filter_options(db, _manage(user))


@router.post("/todo-fines/rules", response_model=TodoFineRuleRead, status_code=status.HTTP_201_CREATED)
def create_rule(payload: TodoFineRuleWrite, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    tenant_id = _manage(user)
    try:
        rule = config.create_rule(db, tenant_id, payload)
    except (SQLAlchemyError, ValueError) as exc:
        raise _bad_request(db, exc, "Rule could not be created") from exc
    audit.log(db, action="todo_fine.rule_created", actor=user, entity_type="todo_fine_rule", entity_id=None, details={"rule": str(rule.id), "name": rule.name})
    return rule


@router.put("/todo-fines/rules/order", status_code=status.HTTP_204_NO_CONTENT)
def order_rules(payload: TodoFineRuleOrder, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    tenant_id = _manage(user)
    try:
        config.reorder_rules(db, tenant_id, payload.ids)
    except (SQLAlchemyError, ValueError) as exc:
        raise _bad_request(db, exc, "Order could not be saved") from exc


@router.put("/todo-fines/rules/{rule_id}", response_model=TodoFineRuleRead)
def update_rule(rule_id: uuid.UUID, payload: TodoFineRuleWrite, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    tenant_id = _manage(user)
    rule = config.get_rule(db, tenant_id, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    try:
        result = config.update_rule(db, tenant_id, rule, payload)
    except (SQLAlchemyError, ValueError) as exc:
        raise _bad_request(db, exc, "Rule could not be saved") from exc
    audit.log(db, action="todo_fine.rule_updated", actor=user, entity_type="todo_fine_rule", entity_id=rule.id, details={"name": result.name})
    return result


@router.delete("/todo-fines/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rule(rule_id: uuid.UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    tenant_id = _manage(user)
    rule = config.get_rule(db, tenant_id, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    internal_id, name = rule.id, rule.name
    # Von Hand zugewiesene Regel (fine_mode "rule"): Löschen setzte fine_rule_id still auf NULL
    # und die Busse fiel weg ("rule_missing"). Solche Regeln nur deaktivieren.
    in_use = config.rule_usage(db, tenant_id, internal_id)
    if in_use:
        raise HTTPException(status_code=409, detail={"code": "rule_in_use", "count": in_use, "message": "Rule is assigned to todos; deactivate it instead"})
    try:
        config.delete_rule(db, rule)
    except SQLAlchemyError as exc:
        raise _bad_request(db, exc, "Rule could not be deleted") from exc
    audit.log(db, action="todo_fine.rule_deleted", actor=user, entity_type="todo_fine_rule", entity_id=internal_id, details={"name": name})


# ── Bussenliste ──────────────────────────────────────────────────────

Collector = aliased(Participant)
Deleter = aliased(Participant)
FinedPerson = aliased(Participant)


def _stored_items(db: Session, tenant_id: int, participant_id: int | None) -> list[TodoFineListItem]:
    """Offene eingefrorene Bussen immer vollständig (die muss jemand bearbeiten); die erledigte
    Historie (einkassiert, erlassen) nur die neuesten LIST_LIMIT."""
    base = _stored_query().where(TodoFine.tenant_id == tenant_id)
    if participant_id is not None:
        base = base.where(TodoFine.participant_id == participant_id)
    pending = base.where(TodoFine.status == "pending").order_by(TodoFine.created_at.desc())
    history = base.where(TodoFine.status != "pending").order_by(TodoFine.created_at.desc()).limit(LIST_LIMIT)
    return [_stored_item(row) for row in db.execute(pending)] + [_stored_item(row) for row in db.execute(history)]


def _stored_item(row) -> TodoFineListItem:
    fine: TodoFine = row[0]
    return TodoFineListItem(
        id=fine.public_id, status=fine.status, todo_id=row.todo_public_id, task=fine.task_snapshot,  # type: ignore[arg-type]
        participant_id=row.participant_public_id, participant_name=fine.participant_name_snapshot,
        tariff_name=fine.tariff_name_snapshot, rule_name=fine.rule_name_snapshot, due_date=fine.due_date,
        completed_on=fine.completed_on, days_late=fine.days_late, amount=fine.amount, account_id=row.account_public_id,
        currency_label=row.currency_label, collected_at=fine.collected_at, collected_by_display_name=row.collector_name,
        delete_comment=fine.delete_comment if fine.status == "deleted" else None, deleted_at=fine.deleted_at,
        deleted_by_display_name=row.deleter_name, can_reopen=fine.status == "collected",
    )


def _open_items(db: Session, tenant_id: int, participant_id: int | None) -> list[TodoFineListItem]:
    items: list[TodoFineListItem] = []
    open_items = fines.open_items(db, tenant_id, participant_id=participant_id)
    people_ids = {line.participant_id for item in open_items for line in item.evaluation.lines}
    people = public_id_service.resolve_public_ids(db, Participant, list(people_ids)) if people_ids else {}
    account_ids = {item.evaluation.account_id for item in open_items if item.evaluation.account_id}
    accounts = {
        row.id: row for row in db.execute(
            select(FinanceAccount.id, FinanceAccount.public_id, FinanceAccount.currency_label).where(
                FinanceAccount.id.in_(account_ids), FinanceAccount.tenant_id == tenant_id
            )
        )
    } if account_ids else {}
    rule_refs = lambda evaluation: [TodoFineRuleRef(id=rule.public_id, name=rule.name) for rule in evaluation.matching]  # noqa: E731
    for item in open_items:
        evaluation, facts = item.evaluation, item.facts
        if evaluation.state == "conflict":
            items.append(TodoFineListItem(
                id=None, status="conflict", todo_id=facts.public_id, task=facts.task, participant_id=None, participant_name=None,
                matching_rules=rule_refs(evaluation), due_date=facts.due, completed_on=facts.completed_on if facts.status_code == "done" else None,
                days_late=evaluation.days_late, amount=Decimal("0"),
            ))
            continue
        for line in evaluation.lines:
            if participant_id is not None and line.participant_id != participant_id:
                continue
            items.append(TodoFineListItem(
                id=None, status="running", todo_id=facts.public_id, task=facts.task, participant_id=people.get(line.participant_id),
                participant_name=line.name, tariff_name=line.tariff_name, rule_name=evaluation.rule.name if evaluation.rule else None,
                due_date=facts.due, days_late=evaluation.days_late, amount=line.amount,
                account_id=account.public_id if (account := accounts.get(evaluation.account_id)) else None,
                currency_label=account.currency_label if account else None,
            ))
    return items


@router.get("/todo-fines", response_model=list[TodoFineListItem])
def list_todo_fines(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    """Laufende Bussen, Konflikte und eingefrorene Bussen. Ohne reports.personal nur die eigenen
    (eigene Daten, keine Permission nötig - wie GET /fines)."""
    require_feature(user, F.TODO_FINES, write=False)
    tenant_id = _tenant(user)
    participant_id = None if user.can(P.REPORTS_PERSONAL) else user.user_id
    open_items = _open_items(db, tenant_id, participant_id)
    if participant_id is not None:
        open_items = [item for item in open_items if item.status != "conflict"]
    return open_items + _stored_items(db, tenant_id, participant_id)


def _fine_id(db: Session, fine_id: uuid.UUID, tenant_id: int) -> int:
    internal_id = public_id_service.resolve_internal_id(db, TodoFine, fine_id, tenant_id=tenant_id)
    if internal_id is None:
        raise HTTPException(status_code=404, detail="Fine not found")
    return internal_id


def _stored_query():
    return (
        select(
            TodoFine,
            ProtocolTodo.public_id.label("todo_public_id"),
            FinedPerson.public_id.label("participant_public_id"),
            FinanceAccount.public_id.label("account_public_id"),
            FinanceAccount.currency_label,
            Collector.display_name.label("collector_name"),
            Deleter.display_name.label("deleter_name"),
        )
        .outerjoin(ProtocolTodo, ProtocolTodo.id == TodoFine.protocol_todo_id)
        .outerjoin(FinedPerson, FinedPerson.id == TodoFine.participant_id)
        .outerjoin(FinanceAccount, FinanceAccount.id == TodoFine.account_id)
        .outerjoin(Collector, Collector.id == TodoFine.collected_by_user_id)
        .outerjoin(Deleter, Deleter.id == TodoFine.deleted_by_user_id)
    )


def _single(db: Session, fine: TodoFine | None) -> TodoFineListItem:
    if fine is None:
        raise HTTPException(status_code=409, detail="Fine status does not allow this action")
    return _stored_item(db.execute(_stored_query().where(TodoFine.id == fine.id)).one())


@router.post("/todo-fines/{fine_id}/collect", response_model=TodoFineListItem)
def collect_todo_fine(fine_id: uuid.UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    tenant_id = _manage(user)
    require_feature(user, F.FINANCE)
    internal_id = _fine_id(db, fine_id, tenant_id)
    try:
        fine = fines.collect(db, internal_id, tenant_id, user.user_id)
    except fines.TodoFineError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        raise _bad_request(db, exc, "Fine could not be collected") from exc
    if fine is not None:
        audit.log(db, action="todo_fine.collected", actor=user, entity_type="todo_fine", entity_id=fine.id, details={"amount": float(fine.amount)})
    return _single(db, fine)


@router.post("/todo-fines/{fine_id}/reopen", response_model=TodoFineListItem)
def reopen_todo_fine(fine_id: uuid.UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    tenant_id = _manage(user)
    internal_id = _fine_id(db, fine_id, tenant_id)
    try:
        fine = fines.reopen(db, internal_id, tenant_id)
    except SQLAlchemyError as exc:
        raise _bad_request(db, exc, "Fine could not be reopened") from exc
    if fine is not None:
        audit.log(db, action="todo_fine.reopened", actor=user, entity_type="todo_fine", entity_id=fine.id)
    return _single(db, fine)


@router.post("/todo-fines/{fine_id}/waive", response_model=TodoFineListItem)
def waive_todo_fine(fine_id: uuid.UUID, payload: TodoFineDelete, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    tenant_id = _manage(user)
    internal_id = _fine_id(db, fine_id, tenant_id)
    try:
        fine = fines.waive(db, internal_id, tenant_id, user.user_id, payload.reason)
    except fines.TodoFineError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        raise _bad_request(db, exc, "Fine could not be waived") from exc
    if fine is not None:
        audit.log(db, action="todo_fine.waived", actor=user, entity_type="todo_fine", entity_id=fine.id, details={"reason": payload.reason})
    return _single(db, fine)


@router.post("/todo-fines/{fine_id}/restore", response_model=TodoFineListItem)
def restore_todo_fine(fine_id: uuid.UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    tenant_id = _manage(user)
    internal_id = _fine_id(db, fine_id, tenant_id)
    try:
        fine = fines.restore(db, internal_id, tenant_id)
    except SQLAlchemyError as exc:
        raise _bad_request(db, exc, "Fine could not be restored") from exc
    if fine is not None:
        audit.log(db, action="todo_fine.restored", actor=user, entity_type="todo_fine", entity_id=fine.id)
    return _single(db, fine)


# ── Busse am Todo ────────────────────────────────────────────────────


def _todo_for(db: Session, user: CurrentUser, todo_id: uuid.UUID) -> ProtocolTodo:
    todo = public_id_service.get_by_public_id(db, ProtocolTodo, todo_id, tenant_id=_tenant(user))
    if todo is None:
        raise HTTPException(status_code=404, detail="Todo not found")
    access_service.ensure_can_read_todo(db, user, todo.id)
    return todo


def _evaluation(db: Session, user: CurrentUser, todo: ProtocolTodo, *, settings: dict | None = None) -> TodoFineEvaluation:
    """``settings`` (nur Vorschau): Einstellung so rechnen, als wäre sie gespeichert."""
    ctx = fines.TenantFineContext(db, todo.tenant_id)
    facts = fines.load_facts(db, todo)
    if facts is None:
        raise HTTPException(status_code=404, detail="Todo not found")
    if settings is not None:
        facts = dataclasses.replace(facts, **settings)
    evaluation = fines.evaluate(ctx, facts)
    can_manage = user.can(P.FINANCES_MANAGE)
    sees_all = can_manage or user.can(P.REPORTS_PERSONAL)
    stored = db.execute(
        select(TodoFine, FinedPerson.public_id).outerjoin(FinedPerson, FinedPerson.id == TodoFine.participant_id)
        .where(TodoFine.protocol_todo_id == todo.id, TodoFine.status != "deleted")
    ).all()
    people = public_id_service.resolve_public_ids(db, Participant, [line.participant_id for line in evaluation.lines])
    # Eingefrorene Bussen bleiben auch nach dem Wiedereröffnen stehen; eine laufende Busse haben nur
    # Personen ohne gespeicherte Busse (erlassene zählen mit, wie in sync_todo).
    with_stored = fines.stored_participants(db, [todo.id]).get(todo.id, set())
    lines = [
        (fine.participant_id, TodoFineLine(participant_id=public_id, participant_name=fine.participant_name_snapshot, tariff_name=fine.tariff_name_snapshot, amount=fine.amount))
        for fine, public_id in stored
    ]
    if facts.status_code in fines.OPEN_STATUS_CODES:
        lines += [
            (line.participant_id, TodoFineLine(participant_id=people.get(line.participant_id), participant_name=line.name, tariff_name=line.tariff_name, amount=line.amount))
            for line in evaluation.lines if line.participant_id not in with_stored
        ]
    elif not stored:
        lines = [
            (line.participant_id, TodoFineLine(participant_id=people.get(line.participant_id), participant_name=line.name, tariff_name=line.tariff_name, amount=line.amount))
            for line in evaluation.lines
        ]
    visible = [line for owner, line in lines if sees_all or owner == user.user_id]
    rule_public = None
    if facts.fine_rule_id:
        rule_public = public_id_service.resolve_public_id(db, TodoFineRule, facts.fine_rule_id)
    return TodoFineEvaluation(
        state=evaluation.state,  # type: ignore[arg-type]
        # Einstellung von Hand nur für die Kasse: ein fixer Betrag verriete sonst die Bussen anderer.
        fine_mode=facts.fine_mode if can_manage else "auto",  # type: ignore[arg-type]
        fine_rule_id=rule_public if can_manage else None,
        fine_fixed_amount=facts.fine_fixed_amount if can_manage else None,
        fine_split_mode=facts.fine_split_mode if can_manage else None,  # type: ignore[arg-type]
        rule_id=evaluation.rule.public_id if evaluation.rule else None,  # type: ignore[arg-type]
        rule_name=evaluation.rule.name if evaluation.rule else None,
        matching_rules=[TodoFineRuleRef(id=rule.public_id, name=rule.name) for rule in evaluation.matching],  # type: ignore[arg-type]
        due_date=evaluation.due,
        days_late=evaluation.days_late,
        running=evaluation.state == "ok" and facts.status_code in fines.OPEN_STATUS_CODES
        and any(line.participant_id not in with_stored for line in evaluation.lines),
        frozen=bool(stored),
        split_mode=evaluation.split_mode,  # type: ignore[arg-type]
        lines=visible,
        total=fines.money(sum((line.amount for line in visible), Decimal("0"))),
        can_manage=can_manage,
        auto_rules=[TodoFineRuleRef(id=rule.public_id, name=rule.name) for rule in fines.matching_rules(ctx, facts)] if can_manage else [],  # type: ignore[arg-type]
        currency=db.scalar(select(Tenant.finance_currency).where(Tenant.id == todo.tenant_id)) or "CHF",
    )


def _settings(db: Session, tenant_id: int, payload: TodoFineSettings) -> dict:
    """Einstellung prüfen und in interne Werte übersetzen (PUT und Vorschau)."""
    rule_id = None
    if payload.fine_mode == "rule":
        if payload.fine_rule_id is None:
            raise HTTPException(status_code=400, detail="Rule is required")
        rule_id = public_id_service.resolve_internal_id(db, TodoFineRule, payload.fine_rule_id, tenant_id=tenant_id)
        if rule_id is None:
            raise HTTPException(status_code=400, detail="Unknown rule")
    if payload.fine_mode == "fixed" and payload.fine_fixed_amount is None:
        raise HTTPException(status_code=400, detail="Amount is required")
    return {
        "fine_mode": payload.fine_mode,
        "fine_rule_id": rule_id,
        "fine_fixed_amount": payload.fine_fixed_amount if payload.fine_mode == "fixed" else None,
        "fine_split_mode": payload.fine_split_mode if payload.fine_mode == "fixed" else None,
    }


@router.get("/protocol-todos/{todo_id}/fine", response_model=TodoFineEvaluation)
def get_todo_fine(todo_id: uuid.UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    """Busse des Todos (laufend, eingefroren oder Grund, warum keine anfällt). Beträge anderer
    Personen nur mit reports.personal oder finances.manage."""
    require_permission(user, P.MEETINGS_READ)
    require_feature(user, F.TODO_FINES, write=False)
    return _evaluation(db, user, _todo_for(db, user, todo_id))


@router.post("/protocol-todos/{todo_id}/fine/preview", response_model=TodoFineEvaluation)
def preview_todo_fine(todo_id: uuid.UUID, payload: TodoFineSettings, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    """Vorschau im Pendenzen-Popup: Beträge je Person für eine noch nicht gespeicherte Einstellung
    (Regel, Fixbetrag, keine Busse). Speichert nichts; nur für die Kasse wie das Festlegen."""
    tenant_id = _manage(user)
    todo = _todo_for(db, user, todo_id)
    return _evaluation(db, user, todo, settings=_settings(db, tenant_id, payload))


@router.put("/protocol-todos/{todo_id}/fine", response_model=TodoFineEvaluation)
def put_todo_fine(todo_id: uuid.UUID, payload: TodoFineSettings, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    """Busse von Hand festlegen: automatisch, bestimmte Regel, fixer Betrag oder keine Busse.
    Ein erledigtes Todo bekommt seine offenen eingefrorenen Bussen neu gerechnet - der einzige Weg
    neben dem Erlassen, eine eingefrorene Busse zu ändern; die verworfenen stehen im Audit-Log."""
    tenant_id = _manage(user)
    todo = _todo_for(db, user, todo_id)
    values = _settings(db, tenant_id, payload)
    todo.fine_mode = values["fine_mode"]
    todo.fine_rule_id = values["fine_rule_id"]
    todo.fine_fixed_amount = values["fine_fixed_amount"]
    todo.fine_split_mode = values["fine_split_mode"]
    try:
        db.flush()
        replaced = fines.sync_todo(db, todo, recalculate=True)
        db.commit()
    except SQLAlchemyError as exc:
        raise _bad_request(db, exc, "Fine could not be saved") from exc
    audit.log(
        db, action="todo_fine.todo_settings_changed", actor=user, entity_type="protocol_todo", entity_id=todo.id,
        details={
            "fine_mode": payload.fine_mode, "fixed": float(payload.fine_fixed_amount) if payload.fine_fixed_amount is not None else None,
            "replaced_pending_fines": replaced,
        },
    )
    db.refresh(todo)
    return _evaluation(db, user, todo)
