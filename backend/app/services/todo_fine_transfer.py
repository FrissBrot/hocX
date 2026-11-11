"""Pendenzen-Bussen beim Export, Import und Klonen eines Mandanten (Migration 0169).

`app_user.fine_tariff_group_id` und `protocol_todo.fine_rule_id` verweisen auf Zeilen dieses
Moduls. Import und Klon setzen sie beim Anlegen der Personen bzw. Todos auf NULL (sonst zeigten
sie auf Tarife/Regeln des Quellmandanten) und tragen sie hier nach, sobald Tarife und Regeln
neu angelegt sind.
"""
from __future__ import annotations

from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    FineTariffGroup,
    Participant,
    ProtocolTodo,
    TaskPackage,
    TodoFine,
    TodoFineRule,
    TodoFineRuleParticipant,
    TodoFineRuleRate,
    TodoFineRuleRole,
    TodoFineRuleTaskPackage,
)
from app.models.entities import TenantRole

TABLES = (
    "fine_tariff_group", "todo_fine_rule", "todo_fine_rule_rate", "todo_fine_rule_task_package",
    "todo_fine_rule_participant", "todo_fine_rule_role", "todo_fine",
)
CHILD_MODELS = {
    "todo_fine_rule_rate": TodoFineRuleRate,
    "todo_fine_rule_task_package": TodoFineRuleTaskPackage,
    "todo_fine_rule_participant": TodoFineRuleParticipant,
    "todo_fine_rule_role": TodoFineRuleRole,
}


# ── Export ───────────────────────────────────────────────────────────


def export_rows(db: Session, tenant_id: int) -> dict[str, list[Any]]:
    """ORM-Zeilen je Tabelle (der Export serialisiert sie selbst)."""
    rule_ids = list(db.scalars(select(TodoFineRule.id).where(TodoFineRule.tenant_id == tenant_id)))
    rows: dict[str, list[Any]] = {
        "fine_tariff_group": list(db.scalars(select(FineTariffGroup).where(FineTariffGroup.tenant_id == tenant_id))),
        "todo_fine_rule": list(db.scalars(select(TodoFineRule).where(TodoFineRule.tenant_id == tenant_id))),
        "todo_fine": list(db.scalars(select(TodoFine).where(TodoFine.tenant_id == tenant_id))),
    }
    for table, model in CHILD_MODELS.items():
        rows[table] = list(db.scalars(select(model).where(model.rule_id.in_(rule_ids)))) if rule_ids else []
    return rows


# ── Gemeinsam für Import und Klon ────────────────────────────────────


def _mapped(id_map: dict[int, int], value: Any) -> int | None:
    return id_map.get(int(value)) if value is not None else None


def restore(
    db: Session,
    new_tenant_id: int,
    *,
    groups: list[dict[str, Any]],
    rules: list[dict[str, Any]],
    children: dict[str, list[dict[str, Any]]],
    fines: list[dict[str, Any]],
    person_groups: dict[int, int | None],
    todo_rules: dict[int, int | None],
    build: Callable[[type, dict[str, Any], dict[str, Any]], Any],
    participant_map: dict[int, int],
    finance_account_map: dict[int, int],
    task_package_map: dict[int, int],
    role_map: dict[int, int],
    todo_map: dict[int, int],
    finance_transaction_map: dict[int, int],
    user_map: Callable[[Any], int | None] = lambda value: None,
) -> None:
    """Legt Tarife, Regeln und Bussen im neuen Mandanten an. Alle Zeilen kommen als Dict mit den
    Werten des Quellmandanten; `build(model, data, overrides)` erzeugt die neue ORM-Zeile.
    `person_groups`/`todo_rules`: alte Personen-/Todo-ID -> alter Tarif/alte Regel."""
    group_map: dict[int, int] = {}
    for row in groups:
        new_row = build(FineTariffGroup, row, {"tenant_id": new_tenant_id})
        db.add(new_row)
        db.flush()
        group_map[row["id"]] = new_row.id
    rule_map: dict[int, int] = {}
    for row in rules:
        new_row = build(TodoFineRule, row, {"tenant_id": new_tenant_id, "account_id": _mapped(finance_account_map, row.get("account_id"))})
        db.add(new_row)
        db.flush()
        rule_map[row["id"]] = new_row.id
    targets = {
        "todo_fine_rule_rate": ("tariff_group_id", group_map),
        "todo_fine_rule_task_package": ("task_package_id", task_package_map),
        "todo_fine_rule_participant": ("participant_id", participant_map),
        "todo_fine_rule_role": ("role_id", role_map),
    }
    for table, (column, id_map) in targets.items():
        for row in children.get(table, []):
            rule_id, target_id = _mapped(rule_map, row.get("rule_id")), _mapped(id_map, row.get(column))
            if rule_id is not None and target_id is not None:
                db.add(build(CHILD_MODELS[table], row, {"rule_id": rule_id, column: target_id}))
    for old_person, old_group in person_groups.items():
        new_person, new_group = _mapped(participant_map, old_person), _mapped(group_map, old_group)
        if new_person is not None and new_group is not None:
            person = db.get(Participant, new_person)
            if person is not None and person.tenant_id == new_tenant_id:
                person.fine_tariff_group_id = new_group
    for old_todo, old_rule in todo_rules.items():
        new_todo, new_rule = _mapped(todo_map, old_todo), _mapped(rule_map, old_rule)
        if new_todo is not None and new_rule is not None:
            todo = db.get(ProtocolTodo, new_todo)
            if todo is not None and todo.tenant_id == new_tenant_id:
                todo.fine_rule_id = new_rule
    for row in fines:
        db.add(build(TodoFine, row, {
            "tenant_id": new_tenant_id,
            "protocol_todo_id": _mapped(todo_map, row.get("protocol_todo_id")),
            "rule_id": _mapped(rule_map, row.get("rule_id")),
            "participant_id": _mapped(participant_map, row.get("participant_id")),
            "account_id": _mapped(finance_account_map, row.get("account_id")),
            "collected_transaction_id": _mapped(finance_transaction_map, row.get("collected_transaction_id")),
            "collected_by_user_id": user_map(row.get("collected_by_user_id")),
            "deleted_by_user_id": user_map(row.get("deleted_by_user_id")),
        }))
    db.commit()


# ── Klon ─────────────────────────────────────────────────────────────


def _as_dict(row: Any) -> dict[str, Any]:
    return {column.key: getattr(row, column.key) for column in row.__table__.columns}


def clone(
    db: Session,
    source_tenant_id: int,
    new_tenant_id: int,
    *,
    copy_row: Callable[[Any, dict[str, Any]], Any],
    participant_map: dict[int, int],
    finance_account_map: dict[int, int],
    todo_map: dict[int, int],
    finance_transaction_map: dict[int, int],
    with_fines: bool,
) -> None:
    """Klon: Tarife und Regeln immer; Personen-Tarife, Todo-Regeln und Bussen nur beim
    Vollklon (with_fines). Aufgabenpakete und Standardrollen werden über Name bzw. system_key
    zugeordnet (beide je Mandant eindeutig); eigene Rollen klont der Klon nicht."""
    source = export_rows(db, source_tenant_id)
    package_map = _match(db, TaskPackage, TaskPackage.name, source_tenant_id, new_tenant_id)
    role_map = _match(db, TenantRole, TenantRole.system_key, source_tenant_id, new_tenant_id)

    def build(model: type, data: dict[str, Any], overrides: dict[str, Any]) -> Any:
        original = data["__orm__"]
        return copy_row(original, overrides)

    def wrap(rows: list[Any]) -> list[dict[str, Any]]:
        return [{**_as_dict(row), "__orm__": row} for row in rows]

    person_groups = dict(db.execute(
        select(Participant.id, Participant.fine_tariff_group_id).where(
            Participant.tenant_id == source_tenant_id, Participant.fine_tariff_group_id.is_not(None)
        )
    ).all()) if with_fines else {}
    todo_rules = dict(db.execute(
        select(ProtocolTodo.id, ProtocolTodo.fine_rule_id).where(
            ProtocolTodo.tenant_id == source_tenant_id, ProtocolTodo.fine_rule_id.is_not(None)
        )
    ).all()) if with_fines else {}
    restore(
        db, new_tenant_id,
        groups=wrap(source["fine_tariff_group"]),
        rules=wrap(source["todo_fine_rule"]),
        children={table: wrap(source[table]) for table in CHILD_MODELS},
        fines=wrap(source["todo_fine"]) if with_fines else [],
        person_groups=person_groups,
        todo_rules=todo_rules,
        build=build,
        participant_map=participant_map,
        finance_account_map=finance_account_map,
        task_package_map=package_map,
        role_map=role_map,
        todo_map=todo_map,
        finance_transaction_map=finance_transaction_map,
    )


def _match(db: Session, model: type, key_column, source_tenant_id: int, new_tenant_id: int) -> dict[int, int]:
    source = {key: row_id for row_id, key in db.execute(select(model.id, key_column).where(model.tenant_id == source_tenant_id, key_column.is_not(None)))}
    target = {key: row_id for row_id, key in db.execute(select(model.id, key_column).where(model.tenant_id == new_tenant_id, key_column.is_not(None)))}
    return {source_id: target[key] for key, source_id in source.items() if key in target}
