"""Aufgabenpakete: wiederkehrende Aufgaben pro Zyklus mit Verantwortlichen aus Listen.

Routen werden wie in den übrigen Route-Tests direkt als Funktionen aufgerufen.
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.routes import task_packages as routes
from app.api.routes import todos as todos_route
from app.models import Participant, ProtocolTodo, TaskPackage, TaskPackageCycle, TaskPackageItem, TodoStatus
from app.schemas.protocol import ProtocolTodoUpdate
from app.schemas.task_package import (
    TaskPackageCreate,
    TaskPackageCycleAssign,
    TaskPackageItemCreate,
    TaskPackageItemUpdate,
    TaskPackageResponsible,
)
from app.services import task_package_service as packages
from app.services.protocol_todo_service import ProtocolTodoService
from app.services.tenant_clone_service import TenantCloneService
from app.services.tenant_export_service import TenantExportService
from app.services.tenant_import_service import TenantImportService

from tests.factories import (
    make_current_user,
    make_cycle_config,
    make_event,
    make_list_definition,
    make_list_entry,
    make_participant,
    make_tenant,
)

todo_service = ProtocolTodoService()

# Zyklus 01.08.-31.07.: 2026-10-12 liegt im Zyklus 2026, 2026-03-01 im Zyklus 2025.
TODAY = date(2026, 10, 12)
LAST_CYCLE_DAY = date(2026, 3, 1)


@pytest.fixture
def setup(db):
    tenant = make_tenant(db, "Pfadi")
    cycle = make_cycle_config(db, tenant.id, name="Scharjahr", reset_month=7, reset_day=31)
    anna = make_participant(db, tenant.id, "Anna")
    ben = make_participant(db, tenant.id, "Ben")
    cleo = make_participant(db, tenant.id, "Cleo")
    aemtli = make_list_definition(
        db, tenant.id, name="Ämtliliste", column_one_title="Ämtli", column_two_title="Personen", column_two_value_type="participants"
    )
    lagerleitung = make_list_entry(
        db, aemtli.id, column_one_value={"text_value": "Lagerleitung"}, column_two_value={"participant_ids": [anna.id, ben.id]}
    )
    return {"tenant": tenant, "cycle": cycle, "anna": anna, "ben": ben, "cleo": cleo, "list": aemtli, "entry": lagerleitung}


def _package(db, s, *, recurrence=None, due_rule=None, start_cycle_year=2026) -> tuple[TaskPackage, TaskPackageItem, TaskPackageCycle]:
    package = TaskPackage(tenant_id=s["tenant"].id, name="Sommerlager")
    db.add(package)
    db.flush()
    item = TaskPackageItem(
        task_package_id=package.id,
        task="Lagerplatz reservieren",
        tags=["Lager"],
        responsible_json=[{"list_definition_id": s["list"].id, "list_entry_id": s["entry"].id}],
        recurrence_json=recurrence or {"type": "once"},
        due_rule_json=due_rule or {"type": "fixed", "month": 3, "day": 31},
    )
    package_cycle = TaskPackageCycle(task_package_id=package.id, cycle_config_id=s["cycle"].id, start_cycle_year=start_cycle_year)
    db.add_all([item, package_cycle])
    db.flush()
    return package, item, package_cycle


def _instances(db, item: TaskPackageItem) -> list[ProtocolTodo]:
    return list(
        db.scalars(
            select(ProtocolTodo).where(ProtocolTodo.task_package_item_id == item.id).order_by(ProtocolTodo.cycle_year, ProtocolTodo.occurrence_key)
        )
    )


def _status_id(db, code: str) -> int:
    return db.scalar(select(TodoStatus.id).where(TodoStatus.code == code))


# ---------------------------------------------------------------------------
# Berechnungen
# ---------------------------------------------------------------------------


def test_occurrences_follow_recurrence_inside_cycle_bounds(db, setup):
    _, item, _ = _package(db, setup)
    cycle = setup["cycle"]
    tenant_id = setup["tenant"].id

    item.recurrence_json = {"type": "monthly", "day_of_month": 31}
    monthly = packages.occurrences_for(db, item, tenant_id=tenant_id, cycle_config=cycle, cycle_year=2026)
    assert len(monthly) == 12
    assert monthly[0].anchor == date(2026, 8, 31)
    assert date(2027, 2, 28) in [o.anchor for o in monthly]  # auf Monatsletzten gekürzt
    assert monthly[-1].anchor == date(2027, 7, 31)

    item.recurrence_json = {"type": "weekly", "weekday": 0}
    weekly = packages.occurrences_for(db, item, tenant_id=tenant_id, cycle_config=cycle, cycle_year=2026)
    assert weekly[0].anchor == date(2026, 8, 3)
    assert all(o.anchor.weekday() == 0 for o in weekly)
    assert weekly[-1].anchor <= date(2027, 7, 31)

    inside = make_event(db, tenant_id, title="Hock", event_date=date(2026, 9, 5))
    inside.tag = "Hock"
    outside = make_event(db, tenant_id, title="Hock alt", event_date=date(2026, 7, 5))
    outside.tag = "Hock"
    cancelled = make_event(db, tenant_id, title="Hock abgesagt", event_date=date(2026, 9, 12), is_cancelled=True)
    cancelled.tag = "Hock"
    db.flush()
    item.recurrence_json = {"type": "events", "event_tag": "Hock"}
    events = packages.occurrences_for(db, item, tenant_id=tenant_id, cycle_config=cycle, cycle_year=2026)
    assert [o.key for o in events] == [f"event:{inside.id}"]


def test_due_rules(db, setup):
    _, item, _ = _package(db, setup)
    cycle = setup["cycle"]
    occurrence = packages.Occurrence("once", date(2026, 8, 1))

    assert packages.due_date_for(item, occurrence, cycle_config=cycle, cycle_year=2026) == date(2027, 3, 31)
    item.due_rule_json = {"type": "fixed", "month": 9, "day": 15}
    assert packages.due_date_for(item, occurrence, cycle_config=cycle, cycle_year=2026) == date(2026, 9, 15)
    item.due_rule_json = {"type": "offset", "offset_days": -3}
    assert packages.due_date_for(item, occurrence, cycle_config=cycle, cycle_year=2026) == date(2026, 7, 29)
    item.due_rule_json = {"type": "none"}
    assert packages.due_date_for(item, occurrence, cycle_config=cycle, cycle_year=2026) is None


# ---------------------------------------------------------------------------
# Erzeugung und Verantwortliche
# ---------------------------------------------------------------------------


def test_sync_creates_one_todo_for_all_people_of_the_aemtli(db, setup):
    package, item, _ = _package(db, setup)

    created, _ = packages.sync_package(db, package, today=TODAY)

    todos = _instances(db, item)
    assert created == 1 and len(todos) == 1
    todo = todos[0]
    assert (todo.cycle_year, todo.occurrence_key, todo.due_date) == (2026, "once", date(2027, 3, 31))
    assert packages.todo_assignee_ids(db, todo.id) == [setup["anna"].id, setup["ben"].id]
    assert todo.assigned_participant_id == setup["anna"].id
    # Beide sehen die Aufgabe unter "Meine Todos", inkl. aller Namen und Paket-Herkunft.
    for person in (setup["anna"], setup["ben"]):
        mine = todo_service.list_todos_for_user(db, setup["tenant"].id, person.id)
        assert [t.id for t in mine] == [todo.public_id]
        assert mine[0].assigned_participant_name == "Anna, Ben"
        assert mine[0].task_package_name == "Sommerlager"
        assert len(mine[0].assigned_participant_ids) == 2
    assert todo_service.list_todos_for_user(db, setup["tenant"].id, setup["cleo"].id) == []


def test_sync_is_idempotent(db, setup):
    package, item, _ = _package(db, setup, recurrence={"type": "monthly", "day_of_month": 1}, due_rule={"type": "offset", "offset_days": 7})
    packages.sync_package(db, package, today=TODAY)
    created, updated = packages.sync_package(db, package, today=TODAY)
    assert (created, updated) == (0, 0)
    assert len(_instances(db, item)) == 12


def test_no_todos_before_start_cycle_or_when_inactive(db, setup):
    package, item, _ = _package(db, setup, start_cycle_year=2027)
    packages.sync_package(db, package, today=TODAY)
    assert _instances(db, item) == []

    package_cycle = db.scalar(select(TaskPackageCycle).where(TaskPackageCycle.task_package_id == package.id))
    package_cycle.start_cycle_year = 2026
    package.is_active = False
    packages.sync_package(db, package, today=TODAY)
    assert _instances(db, item) == []


def test_list_change_updates_current_cycle_but_not_past_cycle(db, setup):
    package, item, _ = _package(db, setup, start_cycle_year=2025)
    packages.sync_package(db, package, today=LAST_CYCLE_DAY)  # Zyklus 2025
    packages.sync_package(db, package, today=TODAY)  # Zyklus 2026
    past, current = _instances(db, item)
    assert (past.cycle_year, current.cycle_year) == (2025, 2026)

    # Neues Scharjahr: Cleo übernimmt das Ämtli.
    setup["entry"].column_two_value_json = {"participant_ids": [setup["cleo"].id]}
    db.flush()
    packages.sync_packages_for_list(db, tenant_id=setup["tenant"].id, list_definition_id=setup["list"].id, today=TODAY)

    assert packages.todo_assignee_ids(db, current.id) == [setup["cleo"].id]
    assert packages.todo_assignee_ids(db, past.id) == [setup["anna"].id, setup["ben"].id]


def test_template_change_updates_open_instances_only_and_respects_manual_edits(db, setup):
    package, item, _ = _package(db, setup, recurrence={"type": "monthly", "day_of_month": 1}, due_rule={"type": "none"})
    packages.sync_package(db, package, today=TODAY)
    first, second, third, *_ = _instances(db, item)
    first.todo_status_id = _status_id(db, "done")
    # Von Hand umbenannt -> der Text gehört jetzt der Person, nicht mehr dem Paket.
    todo_service.update_todo(db, second.id, ProtocolTodoUpdate(task="Eigener Text"))
    assert second.overridden_fields == ["task"]

    item.task = "Lagerplatz definitiv reservieren"
    item.tags = ["Lager", "Wichtig"]
    packages.sync_package(db, package, today=TODAY)

    assert first.task == "Lagerplatz reservieren"  # erledigt: unverändert
    assert second.task == "Eigener Text" and second.tags == ["Lager", "Wichtig"]
    assert third.task == "Lagerplatz definitiv reservieren"


def test_manual_assignment_replaces_aemtli_people_and_sticks(db, setup):
    package, item, _ = _package(db, setup)
    packages.sync_package(db, package, today=TODAY)
    (todo,) = _instances(db, item)

    todo_service.update_todo(db, todo.id, ProtocolTodoUpdate(assigned_participant_id=setup["cleo"].public_id))
    packages.sync_package(db, package, today=TODAY)

    assert packages.todo_assignee_ids(db, todo.id) == [setup["cleo"].id]
    assert "assignees" in todo.overridden_fields


def test_new_tagged_event_adds_occurrence_without_deleting(db, setup):
    package, item, _ = _package(db, setup, recurrence={"type": "events", "event_tag": "Lager"}, due_rule={"type": "offset", "offset_days": -14})
    first = make_event(db, setup["tenant"].id, title="Pfingstlager", event_date=date(2027, 5, 15))
    first.tag = "Lager"
    db.flush()
    packages.sync_package(db, package, today=TODAY)
    assert [t.due_date for t in _instances(db, item)] == [date(2027, 5, 1)]

    second = make_event(db, setup["tenant"].id, title="Sola", event_date=date(2027, 7, 10))
    second.tag = "Lager"
    first.is_cancelled = True
    db.flush()
    packages.sync_packages_for_event_tag(db, tenant_id=setup["tenant"].id, tag="Lager", today=TODAY)

    keys = {t.occurrence_key for t in _instances(db, item)}
    assert keys == {f"event:{first.id}", f"event:{second.id}"}  # abgesagter Termin: Aufgabe bleibt


# ---------------------------------------------------------------------------
# Löschen
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("mode", "remaining_years"), [("all", []), ("future", [2025, 2026]), ("none", [2025, 2026, 2027])])
def test_delete_package_modes(db, setup, mode, remaining_years):
    package, item, _ = _package(db, setup, start_cycle_year=2025)
    packages.sync_package(db, package, today=LAST_CYCLE_DAY)
    packages.sync_package(db, package, today=TODAY)
    # Instanz eines künftigen Zyklus (z. B. nach Umstellung des Stichtags) simulieren.
    packages.sync_package(db, package, today=date(2027, 9, 1))
    todo_ids = [t.id for t in _instances(db, item)]
    assert len(todo_ids) == 3

    packages.delete_package(db, package, mode=mode, today=TODAY)

    remaining = db.scalars(select(ProtocolTodo).where(ProtocolTodo.id.in_(todo_ids)).order_by(ProtocolTodo.cycle_year)).all()
    assert [t.cycle_year for t in remaining] == remaining_years
    assert all(t.task_package_item_id is None for t in remaining)  # werden zu normalen Todos


def test_unassign_cycle_keeps_todos_but_detaches_them(db, setup):
    package, item, package_cycle = _package(db, setup)
    packages.sync_package(db, package, today=TODAY)
    (todo,) = _instances(db, item)

    deleted, kept = packages.unassign_cycle(db, package, package_cycle, mode="none", today=TODAY)

    assert (deleted, kept) == (0, 1)
    db.refresh(todo)
    assert todo.task_package_item_id is None
    assert db.get(TaskPackageCycle, package_cycle.id) is None


# ---------------------------------------------------------------------------
# Routen
# ---------------------------------------------------------------------------


def test_routes_create_assign_preview_and_patch(db, setup):
    tenant = setup["tenant"]
    admin = make_current_user(tenant.id, role="admin")
    package = routes.create_task_package(TaskPackageCreate(name="Scharleitung"), db=db, user=admin)
    responsible = [TaskPackageResponsible(list_definition_id=setup["list"].public_id, list_entry_id=setup["entry"].public_id)]
    package = routes.create_task_package_item(
        package.id, TaskPackageItemCreate(task="Jahresplanung", responsible=responsible), db=db, user=admin
    )
    assert package.items[0].responsible == responsible

    package = routes.assign_task_package_cycle(package.id, TaskPackageCycleAssign(cycle_config_id=setup["cycle"].public_id), db=db, user=admin)
    assert len(package.cycles) == 1
    current_year = package.cycles[0].current_cycle_year
    assert package.todo_count == 1 and package.open_todo_count == 1

    preview = routes.preview_task_package(package.id, cycle_config_id=setup["cycle"].public_id, cycle_year=current_year + 1, db=db, user=admin)
    assert [(e.task, e.assignee_names, e.exists) for e in preview.entries] == [("Jahresplanung", ["Anna", "Ben"], False)]

    item_id = package.items[0].id
    package = routes.update_task_package_item(
        package.id, item_id, TaskPackageItemUpdate(task="Jahresplanung erstellen", responsible=responsible), db=db, user=admin
    )
    todo = db.scalar(select(ProtocolTodo).where(ProtocolTodo.tenant_id == tenant.id))
    assert todo.task == "Jahresplanung erstellen"

    # Standalone-Todo bearbeiten liefert genau dieses Todo zurück.
    result = todos_route.patch_todo(todo.public_id, ProtocolTodoUpdate(todo_status_id=_status_id(db, "done")), db=db, user=make_current_user(tenant.id))
    assert result.id == todo.public_id and result.task_package_name == "Scharleitung"

    removal = routes.delete_task_package(package.id, todos="all", db=db, user=admin)
    assert removal.deleted == 1


def test_routes_reject_foreign_tenant_references_and_non_admins(db, setup):
    other = make_tenant(db, "Andere Abteilung")
    stranger_public_id = make_participant(db, other.id, "Fremd").public_id
    admin = make_current_user(setup["tenant"].id, role="admin")
    package = routes.create_task_package(TaskPackageCreate(name="Sommerlager"), db=db, user=admin)

    with pytest.raises(HTTPException) as error:
        routes.get_task_package(package.id, db=db, user=make_current_user(other.id, role="admin"))
    assert error.value.status_code == 404

    with pytest.raises(HTTPException):
        routes.list_task_packages(db=db, user=make_current_user(setup["tenant"].id, role="writer"))

    # Zuletzt: die Route macht bei 400 ein Rollback, danach sind die Testdaten weg.
    with pytest.raises(HTTPException) as error:
        routes.create_task_package_item(
            package.id, TaskPackageItemCreate(task="X", responsible=[TaskPackageResponsible(participant_id=stranger_public_id)]), db=db, user=admin
        )
    assert error.value.status_code == 400


def test_fixed_due_date_requires_once_recurrence():
    with pytest.raises(ValueError):
        TaskPackageItemCreate(task="X", recurrence={"type": "weekly", "weekday": 1}, due_rule={"type": "fixed", "month": 1, "day": 1})


# ---------------------------------------------------------------------------
# Mandanten-Clone und Export/Import
# ---------------------------------------------------------------------------


def _assert_copied_package(db, new_tenant_id: int, *, source_item: TaskPackageItem) -> None:
    new_package = db.scalar(select(TaskPackage).where(TaskPackage.tenant_id == new_tenant_id))
    new_item = db.scalar(select(TaskPackageItem).where(TaskPackageItem.task_package_id == new_package.id))
    new_cycle = db.scalar(select(TaskPackageCycle).where(TaskPackageCycle.task_package_id == new_package.id))
    new_todo = db.scalar(select(ProtocolTodo).where(ProtocolTodo.tenant_id == new_tenant_id))
    (responsible,) = new_item.responsible_json
    assert new_item.id != source_item.id
    assert responsible["list_entry_id"] != source_item.responsible_json[0]["list_entry_id"]
    assert new_cycle.start_cycle_year == 2026
    assert new_todo.task_package_item_id == new_item.id
    assert new_todo.cycle_config_id == new_cycle.cycle_config_id
    names = {p.display_name for p in db.scalars(select(Participant).where(Participant.id.in_(packages.todo_assignee_ids(db, new_todo.id))))}
    assert names == {"Anna", "Ben"}
    # Die Kopie lebt eigenständig weiter: ein weiterer Lauf erzeugt nichts doppelt.
    assert packages.sync_package(db, new_package, today=TODAY) == (0, 0)


def test_clone_full_copies_packages_and_links_instances(db, setup):
    package, item, _ = _package(db, setup)
    packages.sync_package(db, package, today=TODAY)

    cloned = TenantCloneService().clone_full(db, setup["tenant"].id, "Pfadi (Kopie)")

    _assert_copied_package(db, cloned.id, source_item=item)


def test_export_import_roundtrip_keeps_packages(db, setup):
    package, item, _ = _package(db, setup)
    packages.sync_package(db, package, today=TODAY)

    zip_path, _ = TenantExportService().export(db, setup["tenant"].id, "full")
    try:
        new_tenant, warnings = TenantImportService().import_zip(db, zip_path, "Pfadi (Import)")
    finally:
        zip_path.unlink(missing_ok=True)

    assert warnings == []
    _assert_copied_package(db, new_tenant.id, source_item=item)
