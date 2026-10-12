"""Todos nach dem Abschluss ihres Protokolls und die Momentaufnahme des Protokolls.

Todos leben über ihr Protokoll hinaus: auch nach "abgeschlossen" dürfen sie bearbeitet,
erledigt, gelöscht und neu angelegt werden. Das abgeschlossene Protokoll selbst zeigt den
Stand beim Abschluss (protocol.todos_snapshot_json); beim Zurücksetzen wird dieser verworfen.
"""
from __future__ import annotations

from sqlalchemy import select

from app.api.routes import protocols as protocols_route
from app.api.routes import todos as todos_route
from app.models.entities import Protocol, ProtocolTodo, TodoStatus
from app.repositories.export_repository import ExportRepository
from app.schemas.protocol import ProtocolTodoCreate, ProtocolTodoUpdate, ProtocolUpdate
from app.services.protocol_service import ProtocolService

from tests.factories import (
    make_current_user,
    make_protocol,
    make_protocol_element,
    make_protocol_element_block,
    make_protocol_todo,
    make_template,
    make_tenant,
)

protocol_service = ProtocolService()


def _protocol_with_todo(db, status: str):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, status=status)
    element = make_protocol_element(db, protocol.id)
    block = make_protocol_element_block(db, element.id, configuration_snapshot_json={}, element_type_code="todo")
    todo = make_protocol_todo(db, block.id, task="Offen", tenant_id=tenant.id)
    return tenant, protocol, block, todo


def _status_id(db, code: str) -> int:
    return db.scalar(select(TodoStatus.id).where(TodoStatus.code == code))


def _close(db, protocol: Protocol) -> Protocol:
    return protocol_service.update_protocol(db, protocol.id, ProtocolUpdate(status="abgeschlossen"))


def test_todo_of_closed_protocol_can_be_completed_edited_created_and_deleted(db):
    tenant, _protocol, block, todo = _protocol_with_todo(db, "abgeschlossen")
    user = make_current_user(tenant.id)
    done_id = _status_id(db, "done")

    completed = todos_route.patch_todo(todo.public_id, ProtocolTodoUpdate(todo_status_id=done_id, task="Geändert"), db=db, user=user)
    created = todos_route.create_todo(block.public_id, ProtocolTodoCreate(task="Neu", todo_status_id=1), db=db, user=user)
    deleted = todos_route.delete_todo(todo.public_id, db=db, user=user)

    assert completed.todo_status_id == done_id
    assert completed.task == "Geändert"
    assert completed.tracked_change is None
    assert created.task == "Neu"
    assert created.tracked_change is None
    assert deleted["pending_delete"] is False
    assert db.get(ProtocolTodo, todo.id) is None


def test_closing_freezes_todos_and_closed_protocol_shows_snapshot(db):
    tenant, protocol, block, todo = _protocol_with_todo(db, "durchgeführt")
    user = make_current_user(tenant.id)
    _close(db, protocol)
    db.refresh(protocol)
    assert protocol.todos_snapshot_json is not None

    # Live weiterarbeiten: erledigen, neues Todo, altes löschen ...
    todos_route.patch_todo(todo.public_id, ProtocolTodoUpdate(todo_status_id=_status_id(db, "done")), db=db, user=user)
    todos_route.create_todo(block.public_id, ProtocolTodoCreate(task="Später", todo_status_id=1), db=db, user=user)

    # ... das abgeschlossene Protokoll zeigt trotzdem den Stand beim Abschluss.
    shown = todos_route.list_todos(block.public_id, db=db, user=user)
    assert [(item.id, item.task, item.todo_status_code) for item in shown] == [(todo.public_id, "Offen", "open")]

    todos_route.delete_todo(todo.public_id, db=db, user=user)
    shown = todos_route.list_todos(block.public_id, db=db, user=user)
    assert [item.task for item in shown] == ["Offen"]

    # Export liest ebenfalls die Momentaufnahme.
    export_rows = ExportRepository().list_protocol_todos(db, block.id)
    assert [(row.ProtocolTodo.task, row.todo_status_code) for row in export_rows] == [("Offen", "open")]


def test_revert_discards_snapshot_and_shows_live_todos(db):
    tenant, protocol, block, todo = _protocol_with_todo(db, "durchgeführt")
    user = make_current_user(tenant.id)
    _close(db, protocol)
    todos_route.patch_todo(todo.public_id, ProtocolTodoUpdate(task="Live"), db=db, user=user)

    protocols_route.revert_protocol_status(protocol.public_id, db=db, user=user)

    db.refresh(protocol)
    assert protocol.status == "durchgeführt"
    assert protocol.todos_snapshot_json is None
    assert [item.task for item in todos_route.list_todos(block.public_id, db=db, user=user)] == ["Live"]


def test_closed_protocol_freezes_pending_todos_from_earlier_protocols(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    earlier = make_protocol(db, tenant.id, template.id, protocol_number="P-1", status="abgeschlossen")
    element = make_protocol_element(db, earlier.id, section_name="Sitzungsnotizen")
    block = make_protocol_element_block(db, element.id, configuration_snapshot_json={}, element_type_code="todo")
    todo = make_protocol_todo(db, block.id, task="Aus P-1", tenant_id=tenant.id)
    later = make_protocol(db, tenant.id, template.id, protocol_number="P-2", status="durchgeführt")
    later.protocol_date = earlier.protocol_date.replace(month=2)
    db.flush()
    user = make_current_user(tenant.id)

    _close(db, later)
    # Teilnehmer erledigt die Aufgabe nach dem Abschluss von P-2 selbst.
    todos_route.patch_todo(todo.public_id, ProtocolTodoUpdate(todo_status_id=_status_id(db, "done")), db=db, user=user)

    frozen = protocols_route.get_pending_todos(later.public_id, db=db, user=user)
    assert [(item.task, item.todo_status_code) for item in frozen] == [("Aus P-1", "open")]

    # Ein noch offenes, späteres Protokoll sieht den aktuellen Stand: erledigt.
    next_protocol = make_protocol(db, tenant.id, template.id, protocol_number="P-3", status="geplant")
    next_protocol.protocol_date = earlier.protocol_date.replace(month=3)
    db.flush()
    live = protocols_route.get_pending_todos(next_protocol.public_id, db=db, user=user)
    assert [(item.task, item.todo_status_code) for item in live] == [("Aus P-1", "done")]
