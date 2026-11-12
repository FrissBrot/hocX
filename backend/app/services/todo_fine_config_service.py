"""Einstellungen der Pendenzen-Bussen: Tarife, Tarif je Person, Regeln (Migration 0169).

Alle IDs aus Anfragen werden mit tenant_id aufgelöst; eine fremde oder unbekannte ID ist ein
ValueError (Route: 400) bzw. None (Route: 404).
"""
from __future__ import annotations

import uuid

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.orm import Session

from app.models import (
    ProtocolTodo,
    FinanceAccount,
    FineTariffGroup,
    Participant,
    TaskPackage,
    TodoFineRule,
    TodoFineRuleParticipant,
    TodoFineRuleRate,
    TodoFineRuleRole,
    TodoFineRuleTaskPackage,
)
from app.models.entities import TenantRole
from app.schemas.todo_fines import (
    FineTariffGroupRead,
    FineTariffGroupWrite,
    FineTariffMember,
    TodoFineRuleFilter,
    TodoFineRuleRateRead,
    TodoFineRuleRead,
    TodoFineRuleWrite,
    FilterOption,
    TodoFineFilterOptions,
)
from app.services import public_id_service


def _resolve_all(db: Session, model, public_ids: list[uuid.UUID], tenant_id: int, what: str) -> list[int]:
    ids = list(dict.fromkeys(public_ids))
    resolved = public_id_service.resolve_internal_ids(db, model, ids, tenant_id=tenant_id)
    if len(resolved) != len(ids):
        raise ValueError(f"Unknown {what}")
    return [resolved[i] for i in ids]


# ── Tarife ───────────────────────────────────────────────────────────


def list_groups(db: Session, tenant_id: int) -> list[FineTariffGroupRead]:
    counts = dict(
        db.execute(
            select(Participant.fine_tariff_group_id, func.count())
            .where(Participant.tenant_id == tenant_id, Participant.fine_tariff_group_id.is_not(None))
            .group_by(Participant.fine_tariff_group_id)
        ).all()
    )
    groups = db.scalars(
        select(FineTariffGroup).where(FineTariffGroup.tenant_id == tenant_id).order_by(FineTariffGroup.sort_index, FineTariffGroup.id)
    ).all()
    return [
        FineTariffGroupRead(
            id=g.public_id, name=g.name, sort_index=g.sort_index, is_default=g.is_default, member_count=counts.get(g.id, 0),
            amount_late=g.amount_late, amount_absent=g.amount_absent,
        )
        for g in groups
    ]


def get_group(db: Session, tenant_id: int, group_id: uuid.UUID) -> FineTariffGroup | None:
    return public_id_service.get_by_public_id(db, FineTariffGroup, group_id, tenant_id=tenant_id)


def _set_default(db: Session, tenant_id: int, group: FineTariffGroup) -> None:
    db.execute(
        update(FineTariffGroup).where(FineTariffGroup.tenant_id == tenant_id, FineTariffGroup.id != group.id).values(is_default=False)
    )
    db.flush()
    group.is_default = True


def _name_taken(db: Session, tenant_id: int, name: str, exclude_id: int | None = None) -> bool:
    query = select(FineTariffGroup.id).where(FineTariffGroup.tenant_id == tenant_id, func.lower(FineTariffGroup.name) == name.lower())
    if exclude_id is not None:
        query = query.where(FineTariffGroup.id != exclude_id)
    return db.scalar(query.limit(1)) is not None


def create_group(db: Session, tenant_id: int, payload: FineTariffGroupWrite) -> FineTariffGroup:
    if _name_taken(db, tenant_id, payload.name):
        raise ValueError("Tariff name already exists")
    count = db.scalar(select(func.count()).select_from(FineTariffGroup).where(FineTariffGroup.tenant_id == tenant_id)) or 0
    group = FineTariffGroup(
        tenant_id=tenant_id, name=payload.name, sort_index=count, is_default=False,
        amount_late=payload.amount_late, amount_absent=payload.amount_absent,
    )
    db.add(group)
    db.flush()
    # Der erste Tarif ist immer Standard, sonst hätten Personen ohne Tarif keinen Betrag.
    if payload.is_default or count == 0:
        _set_default(db, tenant_id, group)
    db.commit()
    return group


def update_group(db: Session, tenant_id: int, group: FineTariffGroup, payload: FineTariffGroupWrite) -> FineTariffGroup:
    if _name_taken(db, tenant_id, payload.name, exclude_id=group.id):
        raise ValueError("Tariff name already exists")
    group.name = payload.name
    group.amount_late, group.amount_absent = payload.amount_late, payload.amount_absent
    if payload.is_default and not group.is_default:
        _set_default(db, tenant_id, group)
    db.commit()
    return group


def delete_group(db: Session, tenant_id: int, group: FineTariffGroup) -> None:
    was_default = group.is_default
    db.delete(group)
    db.flush()
    if was_default:
        successor = db.scalar(
            select(FineTariffGroup).where(FineTariffGroup.tenant_id == tenant_id).order_by(FineTariffGroup.sort_index, FineTariffGroup.id).limit(1)
        )
        if successor is not None:
            successor.is_default = True
    db.commit()


def reorder_groups(db: Session, tenant_id: int, public_ids: list[uuid.UUID]) -> None:
    ids = _resolve_all(db, FineTariffGroup, public_ids, tenant_id, "tariff")
    for index, group_id in enumerate(ids):
        db.execute(update(FineTariffGroup).where(FineTariffGroup.id == group_id).values(sort_index=index))
    db.commit()


def list_members(db: Session, tenant_id: int) -> list[FineTariffMember]:
    rows = db.execute(
        select(Participant.public_id, Participant.display_name, Participant.is_active, FineTariffGroup.public_id.label("group_public_id"))
        .outerjoin(FineTariffGroup, FineTariffGroup.id == Participant.fine_tariff_group_id)
        .where(Participant.tenant_id == tenant_id)
        .order_by(func.lower(Participant.display_name))
    ).all()
    return [
        FineTariffMember(participant_id=row.public_id, display_name=row.display_name, tariff_group_id=row.group_public_id, is_active=row.is_active)
        for row in rows
    ]


def assign_member(db: Session, tenant_id: int, participant_id: uuid.UUID, group_id: uuid.UUID | None) -> FineTariffMember | None:
    participant = public_id_service.get_by_public_id(db, Participant, participant_id, tenant_id=tenant_id)
    if participant is None:
        return None
    group = None
    if group_id is not None:
        group = get_group(db, tenant_id, group_id)
        if group is None:
            raise ValueError("Unknown tariff")
    participant.fine_tariff_group_id = group.id if group else None
    db.commit()
    return FineTariffMember(
        participant_id=participant.public_id, display_name=participant.display_name,
        tariff_group_id=group.public_id if group else None, is_active=participant.is_active,
    )


# ── Regeln ───────────────────────────────────────────────────────────


def _rule_read(db: Session, rule: TodoFineRule, *, maps: dict | None = None) -> TodoFineRuleRead:
    maps = maps if maps is not None else _rule_maps(db, [rule.id])
    return TodoFineRuleRead(
        id=rule.public_id, name=rule.name, sort_index=rule.sort_index, is_active=rule.is_active, applies_from=rule.applies_from,
        interval_days=rule.interval_days, split_mode=rule.split_mode,  # type: ignore[arg-type]
        account_id=maps["accounts"].get(rule.account_id) if rule.account_id else None,
        filter=TodoFineRuleFilter(
            tags=list(rule.filter_tags or []),
            task_package_ids=maps["packages"].get(rule.id, []),
            participant_ids=maps["participants"].get(rule.id, []),
            role_ids=maps["roles"].get(rule.id, []),
        ),
        rates=maps["rates"].get(rule.id, []),
    )


def _rule_maps(db: Session, rule_ids: list[int]) -> dict:
    maps: dict = {"packages": {}, "participants": {}, "roles": {}, "rates": {}, "accounts": {}}
    if not rule_ids:
        return maps
    for key, model, column, target in (
        ("packages", TodoFineRuleTaskPackage, TodoFineRuleTaskPackage.task_package_id, TaskPackage),
        ("participants", TodoFineRuleParticipant, TodoFineRuleParticipant.participant_id, Participant),
        ("roles", TodoFineRuleRole, TodoFineRuleRole.role_id, TenantRole),
    ):
        for rule_id, public_id in db.execute(
            select(model.rule_id, target.public_id).join(target, target.id == column).where(model.rule_id.in_(rule_ids))
        ):
            maps[key].setdefault(rule_id, []).append(public_id)
    for rule_id, group_public_id, base, per_interval in db.execute(
        select(TodoFineRuleRate.rule_id, FineTariffGroup.public_id, TodoFineRuleRate.base_amount, TodoFineRuleRate.interval_amount)
        .join(FineTariffGroup, FineTariffGroup.id == TodoFineRuleRate.tariff_group_id)
        .where(TodoFineRuleRate.rule_id.in_(rule_ids))
        .order_by(FineTariffGroup.sort_index, FineTariffGroup.id)
    ):
        maps["rates"].setdefault(rule_id, []).append(
            TodoFineRuleRateRead(tariff_group_id=group_public_id, base_amount=base, interval_amount=per_interval)
        )
    maps["accounts"] = dict(
        db.execute(
            select(FinanceAccount.id, FinanceAccount.public_id)
            .join(TodoFineRule, TodoFineRule.account_id == FinanceAccount.id)
            .where(TodoFineRule.id.in_(rule_ids))
        ).all()
    )
    return maps


def list_rules(db: Session, tenant_id: int) -> list[TodoFineRuleRead]:
    rules = db.scalars(
        select(TodoFineRule).where(TodoFineRule.tenant_id == tenant_id).order_by(TodoFineRule.sort_index, TodoFineRule.id)
    ).all()
    maps = _rule_maps(db, [rule.id for rule in rules])
    return [_rule_read(db, rule, maps=maps) for rule in rules]


def get_rule(db: Session, tenant_id: int, rule_id: uuid.UUID) -> TodoFineRule | None:
    return public_id_service.get_by_public_id(db, TodoFineRule, rule_id, tenant_id=tenant_id)


def _apply_rule(db: Session, tenant_id: int, rule: TodoFineRule, payload: TodoFineRuleWrite) -> None:
    account_id = None
    if payload.account_id is not None:
        account_id = public_id_service.resolve_internal_id(db, FinanceAccount, payload.account_id, tenant_id=tenant_id)
        if account_id is None:
            raise ValueError("Unknown account")
    packages = _resolve_all(db, TaskPackage, payload.filter.task_package_ids, tenant_id, "task package")
    participants = _resolve_all(db, Participant, payload.filter.participant_ids, tenant_id, "participant")
    roles = _resolve_all(db, TenantRole, payload.filter.role_ids, tenant_id, "role")
    group_ids = _resolve_all(db, FineTariffGroup, [rate.tariff_group_id for rate in payload.rates], tenant_id, "tariff")
    rule.name = payload.name
    rule.is_active = payload.is_active
    rule.applies_from = payload.applies_from
    rule.interval_days = payload.interval_days
    rule.split_mode = payload.split_mode
    rule.account_id = account_id
    rule.filter_tags = payload.filter.tags
    db.flush()
    for model in (TodoFineRuleTaskPackage, TodoFineRuleParticipant, TodoFineRuleRole, TodoFineRuleRate):
        db.execute(delete(model).where(model.rule_id == rule.id))
    db.add_all(TodoFineRuleTaskPackage(rule_id=rule.id, task_package_id=i) for i in packages)
    db.add_all(TodoFineRuleParticipant(rule_id=rule.id, participant_id=i) for i in participants)
    db.add_all(TodoFineRuleRole(rule_id=rule.id, role_id=i) for i in roles)
    rates = {}
    for group_id, rate in zip(group_ids, payload.rates):
        rates[group_id] = rate
    db.add_all(
        TodoFineRuleRate(rule_id=rule.id, tariff_group_id=group_id, base_amount=rate.base_amount, interval_amount=rate.interval_amount)
        for group_id, rate in rates.items()
    )


def create_rule(db: Session, tenant_id: int, payload: TodoFineRuleWrite) -> TodoFineRuleRead:
    count = db.scalar(select(func.count()).select_from(TodoFineRule).where(TodoFineRule.tenant_id == tenant_id)) or 0
    rule = TodoFineRule(tenant_id=tenant_id, name=payload.name, sort_index=count, applies_from=payload.applies_from)
    db.add(rule)
    _apply_rule(db, tenant_id, rule, payload)
    db.commit()
    return _rule_read(db, rule)


def update_rule(db: Session, tenant_id: int, rule: TodoFineRule, payload: TodoFineRuleWrite) -> TodoFineRuleRead:
    _apply_rule(db, tenant_id, rule, payload)
    db.commit()
    return _rule_read(db, rule)


def delete_rule(db: Session, rule: TodoFineRule) -> None:
    db.delete(rule)
    db.commit()


def reorder_rules(db: Session, tenant_id: int, public_ids: list[uuid.UUID]) -> None:
    ids = _resolve_all(db, TodoFineRule, public_ids, tenant_id, "rule")
    for index, rule_id in enumerate(ids):
        db.execute(update(TodoFineRule).where(TodoFineRule.id == rule_id).values(sort_index=index))
    db.commit()


def filter_options(db: Session, tenant_id: int) -> TodoFineFilterOptions:
    tags: set[str] = set()
    for todo_tags in db.scalars(
        select(ProtocolTodo.tags).where(ProtocolTodo.tenant_id == tenant_id, ProtocolTodo.tags != text("'[]'::jsonb"))
        .order_by(ProtocolTodo.id.desc()).limit(5000)
    ):
        tags.update(str(tag).strip() for tag in (todo_tags or []) if str(tag).strip())
    packages = db.execute(
        select(TaskPackage.public_id, TaskPackage.name).where(TaskPackage.tenant_id == tenant_id).order_by(func.lower(TaskPackage.name))
    ).all()
    roles = db.execute(
        select(TenantRole.public_id, TenantRole.name, TenantRole.system_key).where(TenantRole.tenant_id == tenant_id).order_by(TenantRole.id)
    ).all()
    people = db.execute(
        select(Participant.public_id, Participant.display_name)
        .where(Participant.tenant_id == tenant_id, Participant.is_active.is_(True))
        .order_by(func.lower(Participant.display_name))
    ).all()
    return TodoFineFilterOptions(
        tags=sorted(tags, key=str.lower)[:500],
        task_packages=[FilterOption(id=row.public_id, name=row.name) for row in packages],
        roles=[FilterOption(id=row.public_id, name=row.name, system_key=row.system_key) for row in roles],
        participants=[FilterOption(id=row.public_id, name=row.display_name) for row in people],
    )
