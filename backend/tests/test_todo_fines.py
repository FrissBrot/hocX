"""Pendenzen-Bussen (Migration 0169, app/services/todo_fine_service.py, routes/todo_fines.py)."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.routes import todo_fines as route
from app.models import FinanceTransaction, ProtocolTodo, TodoFine, TodoStatus
from app.schemas.protocol import ProtocolTodoUpdate
from app.schemas.todo_fines import (
    FineTariffAssignment,
    FineTariffGroupWrite,
    TodoFineDelete,
    TodoFineRuleFilter,
    TodoFineRuleRateWrite,
    TodoFineRuleWrite,
    TodoFineSettings,
)
from app.services import todo_fine_service as fines
from app.services.protocol_todo_service import ProtocolTodoService
from app.services.task_package_service import set_todo_assignees
from tests.factories import (
    DEFAULT_TEST_FEATURES,
    GRANDFATHERED_FEATURES,
    make_current_user,
    make_finance_account,
    make_participant,
    make_protocol_todo,
    make_tenant,
)

FEATURES = DEFAULT_TEST_FEATURES | {"todo_fines"}
TODAY = fines.today()


def _status(db, code: str) -> int:
    return db.scalar(select(TodoStatus.id).where(TodoStatus.code == code))


@pytest.fixture
def setup(db):
    tenant = make_tenant(db, "Bussen", features=GRANDFATHERED_FEATURES + ("finance", "todo_fines"))
    account = make_finance_account(db, tenant.id, "Bussenkasse")
    anna = make_participant(db, tenant.id, "Anna")
    ben = make_participant(db, tenant.id, "Ben")
    manager = make_current_user(tenant.id, role="admin", user_id=anna.id, features=FEATURES)
    learners = route.create_tariff(FineTariffGroupWrite(name="Lernende"), db=db, user=manager)
    earners = route.create_tariff(FineTariffGroupWrite(name="Vollverdiener"), db=db, user=manager)
    route.assign_tariff(ben.public_id, FineTariffAssignment(tariff_group_id=earners.id), db=db, user=manager)
    return {
        "tenant": tenant, "account": account, "anna": anna, "ben": ben, "manager": manager,
        "learners": learners, "earners": earners,
    }


def _rule(db, s, name="Pendenzen", *, tags=(), split="each", interval=1, applies_from=date(2020, 1, 1)):
    return route.create_rule(
        TodoFineRuleWrite(
            name=name, applies_from=applies_from, interval_days=interval, split_mode=split, account_id=s["account"].public_id,
            filter=TodoFineRuleFilter(tags=list(tags)),
            rates=[
                TodoFineRuleRateWrite(tariff_group_id=s["learners"].id, base_amount=Decimal("2"), interval_amount=Decimal("1")),
                TodoFineRuleRateWrite(tariff_group_id=s["earners"].id, base_amount=Decimal("10"), interval_amount=Decimal("5")),
            ],
        ),
        db=db, user=s["manager"],
    )


def _todo(db, s, *, days_late: int, people=("anna",), tags=()) -> ProtocolTodo:
    todo = make_protocol_todo(db, None, task="Material bringen", tenant_id=s["tenant"].id)
    todo.due_date = TODAY - timedelta(days=days_late)
    todo.tags = list(tags)
    set_todo_assignees(db, todo, [s[p].id for p in people])
    db.flush()
    return todo


def _complete(db, todo, on: date | None = None):
    ProtocolTodoService().update_todo(db, todo.id, ProtocolTodoUpdate(todo_status_id=_status(db, "done")))
    if on is not None:
        todo.completed_at = datetime(on.year, on.month, on.day, 12, tzinfo=timezone.utc)
        fines.sync_todo(db, todo, recalculate=True)
        db.commit()


def test_rule_amount_grows_per_full_interval():
    assert fines.rule_amount(Decimal("5"), Decimal("2"), 2, 1) == Decimal("5.00")
    assert fines.rule_amount(Decimal("5"), Decimal("2"), 2, 2) == Decimal("7.00")
    assert fines.rule_amount(Decimal("5"), Decimal("2"), 2, 5) == Decimal("9.00")
    assert fines.rule_amount(Decimal("5"), Decimal("2"), 1, 0) == Decimal("0")


def test_running_fine_uses_tariff_of_each_person(db, setup):
    s = setup
    _rule(db, s)
    todo = _todo(db, s, days_late=3, people=("anna", "ben"))
    result = route.get_todo_fine(todo.public_id, db=db, user=s["manager"])
    assert result.state == "ok" and result.running and not result.frozen
    amounts = {line.participant_name: line.amount for line in result.lines}
    # Anna ohne Tarif -> Standard (erster Tarif "Lernende"): 2 + 3x1; Ben Vollverdiener: 10 + 3x5
    assert amounts == {"Anna": Decimal("5.00"), "Ben": Decimal("25.00")}


def test_split_mode_divides_amount(db, setup):
    s = setup
    _rule(db, s, split="split")
    todo = _todo(db, s, days_late=1, people=("anna", "ben"))
    result = route.get_todo_fine(todo.public_id, db=db, user=s["manager"])
    assert {line.participant_name: line.amount for line in result.lines} == {"Anna": Decimal("1.50"), "Ben": Decimal("7.50")}


def test_two_matching_rules_are_a_conflict_until_resolved_by_hand(db, setup):
    s = setup
    first = _rule(db, s, "Alle")
    _rule(db, s, "Material", tags=("material",))
    todo = _todo(db, s, days_late=2, tags=("Material",))
    result = route.get_todo_fine(todo.public_id, db=db, user=s["manager"])
    assert result.state == "conflict" and {r.name for r in result.matching_rules} == {"Alle", "Material"}
    listed = route.list_todo_fines(db=db, user=s["manager"])
    assert [item.status for item in listed] == ["conflict"]

    resolved = route.put_todo_fine(todo.public_id, TodoFineSettings(fine_mode="rule", fine_rule_id=first.id), db=db, user=s["manager"])
    assert resolved.state == "ok" and resolved.rule_name == "Alle"


def test_rule_with_tag_filter_ignores_other_todos_and_applies_from(db, setup):
    s = setup
    _rule(db, s, tags=("material",))
    other = _todo(db, s, days_late=2, tags=("putzen",))
    assert route.get_todo_fine(other.public_id, db=db, user=s["manager"]).state == "no_rule"
    _rule(db, s, "Neu", applies_from=TODAY)
    old = _todo(db, s, days_late=2)
    assert route.get_todo_fine(old.public_id, db=db, user=s["manager"]).state == "no_rule"


def test_fixed_fine_and_no_fine_override_rules(db, setup):
    s = setup
    _rule(db, s)
    todo = _todo(db, s, days_late=4, people=("anna", "ben"))
    fixed = route.put_todo_fine(
        todo.public_id, TodoFineSettings(fine_mode="fixed", fine_fixed_amount=Decimal("20"), fine_split_mode="split"), db=db, user=s["manager"]
    )
    assert fixed.state == "ok" and [line.amount for line in fixed.lines] == [Decimal("10.00"), Decimal("10.00")]
    none = route.put_todo_fine(todo.public_id, TodoFineSettings(fine_mode="none"), db=db, user=s["manager"])
    assert none.state == "none" and none.lines == []


def test_completing_late_freezes_and_reopening_keeps_frozen_fines(db, setup):
    s = setup
    _rule(db, s)
    todo = _todo(db, s, days_late=5, people=("anna", "ben"))
    _complete(db, todo, on=TODAY - timedelta(days=3))  # 2 Tage zu spät erledigt
    stored = {f.participant_name_snapshot: f for f in db.scalars(select(TodoFine).where(TodoFine.protocol_todo_id == todo.id))}
    assert {name: f.amount for name, f in stored.items()} == {"Anna": Decimal("4.00"), "Ben": Decimal("20.00")}
    assert all(f.status == "pending" and f.days_late == 2 for f in stored.values())

    # Einkassieren bucht auf das Konto der Regel
    collected = route.collect_todo_fine(stored["Ben"].public_id, db=db, user=s["manager"])
    assert collected.status == "collected"
    tx = db.scalar(select(FinanceTransaction).where(FinanceTransaction.account_id == s["account"].id))
    assert tx is not None and tx.amount == Decimal("20.00")

    # Wieder geöffnet: eingefroren bleibt eingefroren (Bereichs-Audit 2026-11) - Annas offene und
    # Bens einkassierte Busse bleiben, und es läuft keine zweite Busse für dieselben Personen.
    ProtocolTodoService().update_todo(db, todo.id, ProtocolTodoUpdate(todo_status_id=_status(db, "open")))
    remaining = db.scalars(select(TodoFine).where(TodoFine.protocol_todo_id == todo.id).order_by(TodoFine.participant_name_snapshot)).all()
    assert [(f.participant_name_snapshot, f.status, f.amount) for f in remaining] == [
        ("Anna", "pending", Decimal("4.00")), ("Ben", "collected", Decimal("20.00")),
    ]
    assert [item for item in fines.open_items(db, s["tenant"].id) if item.facts.id == todo.id] == []
    reopened = route.get_todo_fine(todo.public_id, db=db, user=s["manager"])
    assert reopened.frozen and not reopened.running and len(reopened.lines) == 2

    # Erneut erledigt: keine zweite Busse, Betrag unverändert
    _complete(db, todo)
    again = db.scalars(select(TodoFine).where(TodoFine.protocol_todo_id == todo.id)).all()
    assert sorted((f.participant_name_snapshot, f.amount) for f in again) == [("Anna", Decimal("4.00")), ("Ben", Decimal("20.00"))]


def test_on_time_or_cancelled_todos_have_no_fine(db, setup):
    s = setup
    _rule(db, s)
    todo = _todo(db, s, days_late=0)
    _complete(db, todo)
    assert db.scalar(select(TodoFine.id).where(TodoFine.protocol_todo_id == todo.id)) is None
    late = _todo(db, s, days_late=3)
    ProtocolTodoService().update_todo(db, late.id, ProtocolTodoUpdate(todo_status_id=_status(db, "cancelled")))
    assert db.scalar(select(TodoFine.id).where(TodoFine.protocol_todo_id == late.id)) is None


def test_switched_off_module_freezes_nothing(db, setup):
    s = setup
    _rule(db, s)
    from app.models import TenantFeature

    db.query(TenantFeature).filter(TenantFeature.tenant_id == s["tenant"].id, TenantFeature.feature_code == "todo_fines").delete()
    todo = _todo(db, s, days_late=3)
    _complete(db, todo)
    assert db.scalar(select(TodoFine.id).where(TodoFine.protocol_todo_id == todo.id)) is None


def test_waive_requires_reason_and_restore(db, setup):
    s = setup
    _rule(db, s)
    todo = _todo(db, s, days_late=3)
    _complete(db, todo)
    fine = db.scalar(select(TodoFine).where(TodoFine.protocol_todo_id == todo.id))
    waived = route.waive_todo_fine(fine.public_id, TodoFineDelete(reason="Krank"), db=db, user=s["manager"])
    assert waived.status == "deleted" and waived.delete_comment == "Krank"
    assert route.restore_todo_fine(fine.public_id, db=db, user=s["manager"]).status == "pending"


def test_list_shows_only_own_fines_without_reports_personal(db, setup):
    s = setup
    _rule(db, s)
    _todo(db, s, days_late=2, people=("anna",))
    _todo(db, s, days_late=2, people=("ben",))
    reader = make_current_user(s["tenant"].id, role="reader", user_id=s["ben"].id, features=FEATURES)
    items = route.list_todo_fines(db=db, user=reader)
    assert {item.participant_name for item in items} == {"Ben"}
    assert len(route.list_todo_fines(db=db, user=s["manager"])) == 2


def test_feature_and_permission_gate(db, setup):
    s = setup
    writer = make_current_user(s["tenant"].id, role="writer", features=FEATURES)
    with pytest.raises(HTTPException) as exc:
        route.create_tariff(FineTariffGroupWrite(name="X"), db=db, user=writer)
    assert exc.value.status_code == 403
    without_module = make_current_user(s["tenant"].id, role="admin", features=DEFAULT_TEST_FEATURES)
    with pytest.raises(HTTPException) as exc:
        route.list_rules(db=db, user=without_module)
    assert exc.value.status_code == 403
    reader = make_current_user(s["tenant"].id, role="reader", features=FEATURES)
    with pytest.raises(HTTPException):
        route.list_tariff_members(db=db, user=reader)


def test_foreign_tenant_ids_are_rejected(db, setup):
    s = setup
    other = make_tenant(db, "Andere", features=GRANDFATHERED_FEATURES + ("finance", "todo_fines"))
    foreign_manager = make_current_user(other.id, role="admin", features=FEATURES)
    rule = _rule(db, s)
    with pytest.raises(HTTPException) as exc:
        route.update_rule(rule.id, TodoFineRuleWrite(name="x", applies_from=TODAY), db=db, user=foreign_manager)
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        route.assign_tariff(s["anna"].public_id, FineTariffAssignment(), db=db, user=foreign_manager)
    assert exc.value.status_code == 404
    todo = _todo(db, s, days_late=1)
    with pytest.raises(HTTPException) as exc:
        route.get_todo_fine(todo.public_id, db=db, user=foreign_manager)
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        route.collect_todo_fine(uuid.uuid4(), db=db, user=foreign_manager)
    assert exc.value.status_code == 404
    # Zuletzt: ein 400 rollt die Testtransaktion zurück
    with pytest.raises(HTTPException) as exc:
        route.create_rule(
            TodoFineRuleWrite(name="x", applies_from=TODAY, rates=[TodoFineRuleRateWrite(tariff_group_id=s["learners"].id)]),
            db=db, user=foreign_manager,
        )
    assert exc.value.status_code == 400


def test_filter_options_list_names_for_the_cashier(db, setup):
    s = setup
    todo = _todo(db, s, days_late=1, tags=("Material", "putzen"))
    assert todo.tags
    options = route.get_filter_options(db=db, user=s["manager"])
    assert {"Material", "putzen"} <= set(options.tags)
    assert {p.name for p in options.participants} >= {"Anna", "Ben"}
    assert {r.system_key for r in options.roles} >= {"admin", "kassier"}


def _transfer_setup(db, s):
    """Regel mit Personen- und Rollenfilter, Tarif je Person, Regel am Todo und fixierte Busse."""
    from app.models import Participant, TodoFineRule
    from app.models.entities import TenantRole

    kassier = db.scalar(select(TenantRole).where(TenantRole.tenant_id == s["tenant"].id, TenantRole.system_key == "kassier"))
    rule = route.create_rule(
        TodoFineRuleWrite(
            name="Alle", applies_from=date(2020, 1, 1), account_id=s["account"].public_id,
            filter=TodoFineRuleFilter(participant_ids=[s["anna"].public_id, s["ben"].public_id], role_ids=[]),
            rates=[TodoFineRuleRateWrite(tariff_group_id=s["earners"].id, base_amount=Decimal("10"), interval_amount=Decimal("5"))],
        ),
        db=db, user=s["manager"],
    )
    db.add(__import__("app.models", fromlist=["TodoFineRuleRole"]).TodoFineRuleRole(
        rule_id=db.scalar(select(TodoFineRule.id).where(TodoFineRule.public_id == rule.id)), role_id=kassier.id,
    ))
    todo = _todo(db, s, days_late=3, people=("ben",))
    route.put_todo_fine(todo.public_id, TodoFineSettings(fine_mode="rule", fine_rule_id=rule.id), db=db, user=s["manager"])
    _complete(db, todo)
    assert db.get(Participant, s["ben"].id).fine_tariff_group_id is not None
    return rule


def _assert_transferred(db, new_tenant_id: int, *, with_fines: bool):
    from app.models import FineTariffGroup, Participant, TodoFineRule, TodoFineRuleRate, TodoFineRuleRole

    groups = {g.id: g for g in db.scalars(select(FineTariffGroup).where(FineTariffGroup.tenant_id == new_tenant_id))}
    assert {g.name for g in groups.values()} == {"Lernende", "Vollverdiener"}
    rule = db.scalar(select(TodoFineRule).where(TodoFineRule.tenant_id == new_tenant_id))
    assert rule is not None and rule.name == "Alle"
    rate = db.scalar(select(TodoFineRuleRate).where(TodoFineRuleRate.rule_id == rule.id))
    assert rate.tariff_group_id in groups and rate.base_amount == Decimal("10.00")
    role_ids = set(db.scalars(select(TodoFineRuleRole.role_id).where(TodoFineRuleRole.rule_id == rule.id)))
    from app.models.entities import TenantRole
    assert role_ids and all(db.get(TenantRole, rid).tenant_id == new_tenant_id for rid in role_ids)
    # Kein Verweis darf auf den Quellmandanten zeigen
    for person in db.scalars(select(Participant).where(Participant.tenant_id == new_tenant_id)):
        assert person.fine_tariff_group_id is None or person.fine_tariff_group_id in groups
    for todo in db.scalars(select(ProtocolTodo).where(ProtocolTodo.tenant_id == new_tenant_id)):
        assert todo.fine_rule_id in (None, rule.id)
    fines_rows = db.scalars(select(TodoFine).where(TodoFine.tenant_id == new_tenant_id)).all()
    if with_fines:
        assert [(f.participant_name_snapshot, f.amount) for f in fines_rows] == [("Ben", Decimal("25.00"))]
        assert db.get(Participant, fines_rows[0].participant_id).tenant_id == new_tenant_id
        ben = db.get(Participant, fines_rows[0].participant_id)
        assert groups[ben.fine_tariff_group_id].name == "Vollverdiener"
        todo = db.get(ProtocolTodo, fines_rows[0].protocol_todo_id)
        assert todo.tenant_id == new_tenant_id and todo.fine_mode == "rule" and todo.fine_rule_id == rule.id
    else:
        assert fines_rows == []


def test_clone_full_and_structure_copy_todo_fines_without_cross_tenant_links(db, setup):
    from app.services.tenant_clone_service import TenantCloneService

    s = setup
    _transfer_setup(db, s)
    full = TenantCloneService().clone_full(db, s["tenant"].id, "Bussen (Kopie)")
    _assert_transferred(db, full.id, with_fines=True)
    structure = TenantCloneService().clone_structure(db, s["tenant"].id, "Bussen (Struktur)")
    _assert_transferred(db, structure.id, with_fines=False)


def test_export_import_roundtrip_keeps_todo_fines(db, setup):
    from tests.test_tenant_export_import import _export_import

    s = setup
    _transfer_setup(db, s)
    new_tenant, _warnings = _export_import(db, s["tenant"].id, new_name="Bussen (Import)")
    _assert_transferred(db, new_tenant.id, with_fines=True)


def test_personal_data_export_lists_own_todo_fines_and_tariff(db, setup):
    from app.services.data_export import personal

    s = setup
    _rule(db, s)
    todo = _todo(db, s, days_late=2, people=("anna", "ben"))
    _complete(db, todo)
    data = personal.collect(db, s["ben"])
    assert data["person"][0]["fine_tariff"] == "Vollverdiener"
    assert [(row["task"], row["amount"], row["days_late"]) for row in data["todo_fines"]] == [("Material bringen", Decimal("20.00"), 2)]
    assert all(row["task"] for row in personal.collect(db, s["anna"])["todo_fines"])


def test_member_sees_only_own_line_and_no_manual_settings(db, setup):
    s = setup
    todo = _todo(db, s, days_late=2, people=("anna", "ben"))
    route.put_todo_fine(todo.public_id, TodoFineSettings(fine_mode="fixed", fine_fixed_amount=Decimal("30")), db=db, user=s["manager"])
    member = make_current_user(s["tenant"].id, role="reader", user_id=s["ben"].id, features=FEATURES)
    result = route.get_todo_fine(todo.public_id, db=db, user=member)
    assert [line.participant_name for line in result.lines] == ["Ben"]
    assert result.fine_fixed_amount is None and result.fine_mode == "auto" and not result.can_manage


# ── Bereichs-Audit 2026-11 ───────────────────────────────────────────


def _patch(db, todo, user, **values):
    from app.api.routes import todos as todos_route

    return todos_route.patch_todo(todo.public_id, ProtocolTodoUpdate(**values), db=db, user=user)


def _writer(s, person: str):
    return make_current_user(s["tenant"].id, role="writer", user_id=s[person].id, features=FEATURES)


def _audit_actions(db, todo) -> list[str]:
    from sqlalchemy import text

    return list(db.scalars(
        text("SELECT action FROM audit_log WHERE entity_type = 'protocol_todo' AND entity_id = :id"), {"id": todo.id}
    ))


def test_saving_done_todo_again_keeps_completed_at_and_creates_no_fine(db, setup):
    """Hoch 1: das Popup schickt den Status immer mit - Speichern einer pünktlich erledigten
    Pendenz darf completed_at nicht neu setzen (und damit keine Busse auslösen)."""
    s = setup
    _rule(db, s)
    todo = _todo(db, s, days_late=11)
    punctual = TODAY - timedelta(days=12)
    _complete(db, todo, on=punctual)
    assert db.scalar(select(TodoFine.id).where(TodoFine.protocol_todo_id == todo.id)) is None
    before = db.get(ProtocolTodo, todo.id).completed_at

    _patch(db, todo, s["manager"], task="Material bringen (mit Notiz)", todo_status_id=_status(db, "done"))

    db.refresh(todo)
    assert todo.completed_at == before
    assert db.scalar(select(TodoFine.id).where(TodoFine.protocol_todo_id == todo.id)) is None


def test_status_change_between_done_and_open_sets_and_clears_completed_at(db, setup):
    s = setup
    todo = _todo(db, s, days_late=0)
    service = ProtocolTodoService()
    service.update_todo(db, todo.id, ProtocolTodoUpdate(todo_status_id=_status(db, "done")))
    assert db.get(ProtocolTodo, todo.id).completed_at is not None
    service.update_todo(db, todo.id, ProtocolTodoUpdate(todo_status_id=_status(db, "open")))
    assert db.get(ProtocolTodo, todo.id).completed_at is None


def test_todo_created_as_done_gets_completed_at(db, setup):
    from app.schemas.protocol import ProtocolTodoCreate

    s = setup
    todo = ProtocolTodoService().create_standalone_todo(
        db, s["tenant"].id, ProtocolTodoCreate(task="Schon erledigt", todo_status_id=_status(db, "done")), actor_user_id=s["anna"].id,
    )
    assert todo.completed_at is not None and todo.fine_evaluated_at is not None


def test_frozen_fine_survives_due_and_assignee_changes_and_delete(db, setup):
    """Hoch 2: Fälligkeit, Verantwortliche und Löschen lassen eingefrorene Bussen stehen."""
    from app.api.routes import todos as todos_route

    s = setup
    _rule(db, s)
    todo = _todo(db, s, days_late=5, people=("ben",))
    _complete(db, todo, on=TODAY - timedelta(days=3))
    fine = db.scalar(select(TodoFine).where(TodoFine.protocol_todo_id == todo.id))
    assert fine.status == "pending" and fine.amount == Decimal("20.00")

    ben = _writer(s, "ben")
    _patch(db, todo, ben, due_date=TODAY, assigned_participant_ids=[s["anna"].public_id])
    db.refresh(fine)
    assert fine.status == "pending" and fine.amount == Decimal("20.00")
    assert "todo.fine_relevant_changed" in _audit_actions(db, todo)

    todos_route.delete_todo(todo.public_id, db=db, user=ben)
    db.refresh(fine)
    assert fine.status == "pending" and fine.protocol_todo_id is None and fine.task_snapshot == "Material bringen"


def test_fined_person_cannot_remove_own_running_fine(db, setup):
    from app.api.routes import todos as todos_route

    s = setup
    _rule(db, s)
    todo = _todo(db, s, days_late=4, people=("ben",))
    ben = _writer(s, "ben")
    for values in ({"due_date": TODAY}, {"assigned_participant_ids": [s["anna"].public_id]}, {"tags": ["anders"]},
                   {"todo_status_id": _status(db, "cancelled")}):
        with pytest.raises(HTTPException) as exc:
            _patch(db, todo, ben, **values)
        assert exc.value.status_code == 409 and exc.value.detail["code"] == "todo_fine_running"
    with pytest.raises(HTTPException) as exc:
        todos_route.delete_todo(todo.public_id, db=db, user=ben)
    assert exc.value.status_code == 409

    # Unveränderte Werte (das Popup schickt alles mit) und Erledigen sind erlaubt
    _patch(db, todo, ben, task="Material bringen", due_date=todo.due_date, assigned_participant_ids=[s["ben"].public_id])
    # Jemand anderes darf verschieben - nachvollziehbar im Audit-Log
    _patch(db, todo, _writer(s, "anna"), due_date=TODAY)
    assert "todo.fine_relevant_changed" in _audit_actions(db, todo)


def test_cashier_recalculation_replaces_pending_fine_with_audit(db, setup):
    s = setup
    _rule(db, s)
    todo = _todo(db, s, days_late=3)
    _complete(db, todo)
    route.put_todo_fine(todo.public_id, TodoFineSettings(fine_mode="fixed", fine_fixed_amount=Decimal("7")), db=db, user=s["manager"])
    stored = db.scalars(select(TodoFine).where(TodoFine.protocol_todo_id == todo.id)).all()
    assert [(f.amount, f.status) for f in stored] == [(Decimal("7.00"), "pending")]
    assert "todo_fine.todo_settings_changed" in _audit_actions(db, todo)


def test_split_fixed_amount_keeps_every_cent(db, setup):
    s = setup
    carl = make_participant(db, s["tenant"].id, "Carl")
    s["carl"] = carl
    todo = _todo(db, s, days_late=2, people=("anna", "ben", "carl"))
    result = route.put_todo_fine(
        todo.public_id, TodoFineSettings(fine_mode="fixed", fine_fixed_amount=Decimal("10"), fine_split_mode="split"), db=db, user=s["manager"]
    )
    assert [line.amount for line in result.lines] == [Decimal("3.34"), Decimal("3.33"), Decimal("3.33")]


def test_rule_assigned_by_hand_cannot_be_deleted(db, setup):
    s = setup
    rule = _rule(db, s)
    todo = _todo(db, s, days_late=1)
    route.put_todo_fine(todo.public_id, TodoFineSettings(fine_mode="rule", fine_rule_id=rule.id), db=db, user=s["manager"])
    with pytest.raises(HTTPException) as exc:
        route.delete_rule(rule.id, db=db, user=s["manager"])
    assert exc.value.status_code == 409 and exc.value.detail["code"] == "rule_in_use" and exc.value.detail["count"] == 1


def test_restored_fine_on_reopened_todo_is_not_doubled(db, setup):
    s = setup
    _rule(db, s)
    todo = _todo(db, s, days_late=3)
    _complete(db, todo)
    fine = db.scalar(select(TodoFine).where(TodoFine.protocol_todo_id == todo.id))
    route.waive_todo_fine(fine.public_id, TodoFineDelete(reason="Versehen"), db=db, user=s["manager"])
    ProtocolTodoService().update_todo(db, todo.id, ProtocolTodoUpdate(todo_status_id=_status(db, "open")))
    route.restore_todo_fine(fine.public_id, db=db, user=s["manager"])
    listed = [item for item in route.list_todo_fines(db=db, user=s["manager"]) if item.todo_id == todo.public_id]
    assert [item.status for item in listed] == ["pending"]
    _complete(db, todo)
    assert len(db.scalars(select(TodoFine).where(TodoFine.protocol_todo_id == todo.id)).all()) == 1


def test_trigger_completion_is_frozen_even_after_days(db, setup):
    from app.services.submission_service import SubmissionService

    s = setup
    _rule(db, s)
    todo = _todo(db, s, days_late=10)
    todo.todo_status_id = _status(db, "done")
    todo.completed_at = datetime.now(timezone.utc) - timedelta(days=5)  # Abgleich lange ausgefallen
    db.flush()
    SubmissionService._freeze_fines_after_trigger(db, todo)
    SubmissionService._freeze_fines_after_trigger(db, todo)
    stored = db.scalars(select(TodoFine).where(TodoFine.protocol_todo_id == todo.id)).all()
    assert len(stored) == 1 and stored[0].days_late == 5


def test_running_fines_list_has_account_and_constant_query_count(db, setup):
    from tests.test_fines_query_count import _SelectCounter

    s = setup
    _rule(db, s)
    _todo(db, s, days_late=2, people=("anna",))
    db.expire_all()
    with _SelectCounter(db) as small:
        first = route.list_todo_fines(db=db, user=s["manager"])
    for index in range(6):
        extra = make_participant(db, s["tenant"].id, f"Person {index}")
        s[f"p{index}"] = extra
        _todo(db, s, days_late=2, people=(f"p{index}",))
    db.expire_all()
    with _SelectCounter(db) as large:
        many = route.list_todo_fines(db=db, user=s["manager"])
    assert len(first) == 1 and len(many) == 7
    assert all(item.account_id == s["account"].public_id for item in many)
    assert large.count == small.count


def test_todo_routes_answer_404_for_foreign_tenant(db, setup):
    from app.api.routes import todos as todos_route

    s = setup
    todo = _todo(db, s, days_late=0)
    other = make_tenant(db, "Fremd", features=GRANDFATHERED_FEATURES + ("finance", "todo_fines"))
    foreign = make_current_user(other.id, role="admin", features=FEATURES)
    calls = (
        lambda: todos_route.patch_todo(todo.public_id, ProtocolTodoUpdate(task="x"), db=db, user=foreign),
        lambda: todos_route.delete_todo(todo.public_id, db=db, user=foreign),
        lambda: todos_route.get_todo_due_events(todo.public_id, db=db, user=foreign),
        lambda: todos_route.get_todo_details(todo.public_id, db=db, user=foreign),
        lambda: todos_route.accept_todo_tracked_change(todo.public_id, db=db, user=foreign),
    )
    for call in calls:
        with pytest.raises(HTTPException) as exc:
            call()
        assert exc.value.status_code == 404
