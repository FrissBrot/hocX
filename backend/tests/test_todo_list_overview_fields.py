"""Zusatzfelder der Pendenzenliste für die Übersicht v2 (Liste nach Fälligkeit, Board je Person).

- assigned_participant_names: Namen in derselben Reihenfolge wie assigned_participant_ids
- due_session_title: Titel der nächsten Sitzung bei Fälligkeit «nächste Sitzung»
- submission_title: Titel der Abgabe, die die Pendenz automatisch schliesst (nur eigener Mandant)
"""
from __future__ import annotations

from datetime import date

from app.models.entities import ProtocolTodoAssignee, SubmissionAssignment
from app.schemas.protocol import ProtocolTodoCreate
from app.services.protocol_todo_service import ProtocolTodoService

from tests.factories import (
    make_event,
    make_participant,
    make_protocol,
    make_protocol_element,
    make_protocol_element_block,
    make_protocol_todo,
    make_template,
    make_tenant,
)

service = ProtocolTodoService()


def _item(db, tenant_id: int, todo):
    return next(row for row in service.list_todos_for_tenant(db, tenant_id) if row.id == todo.public_id)


def test_assignee_names_follow_assignee_ids(db):
    tenant = make_tenant(db, "Tenant Board")
    anna, ben = make_participant(db, tenant.id, "Anna Muster"), make_participant(db, tenant.id, "Ben Beispiel")
    todo = service.create_standalone_todo(db, tenant.id, ProtocolTodoCreate(task="Zwei Personen", todo_status_id=1))
    todo.assigned_participant_id = ben.id
    db.add_all([
        ProtocolTodoAssignee(protocol_todo_id=todo.id, participant_id=ben.id, sort_index=0),
        ProtocolTodoAssignee(protocol_todo_id=todo.id, participant_id=anna.id, sort_index=1),
    ])
    db.flush()

    item = _item(db, tenant.id, todo)
    assert item.assigned_participant_ids == [ben.public_id, anna.public_id]
    assert item.assigned_participant_names == ["Ben Beispiel", "Anna Muster"]


def test_single_main_assignee_and_unassigned(db):
    tenant = make_tenant(db, "Tenant Einzel")
    anna = make_participant(db, tenant.id, "Anna Muster")
    single = service.create_standalone_todo(db, tenant.id, ProtocolTodoCreate(task="Eine Person", todo_status_id=1))
    single.assigned_participant_id = anna.id
    nobody = service.create_standalone_todo(db, tenant.id, ProtocolTodoCreate(task="Niemand", todo_status_id=1))
    db.flush()

    assert _item(db, tenant.id, single).assigned_participant_names == ["Anna Muster"]
    assert _item(db, tenant.id, nobody).assigned_participant_names == []


def test_next_session_title_and_submission_title(db):
    tenant = make_tenant(db, "Tenant Quelle")
    template = make_template(db, tenant.id)
    template.next_event_id = make_event(db, tenant.id, title="Hock 15", event_date=date(2026, 12, 1)).id
    protocol = make_protocol(db, tenant.id, template.id)
    block = make_protocol_element_block(db, make_protocol_element(db, protocol.id).id, {}, element_type_code="todo")
    todo = make_protocol_todo(db, block.id, task="Bis zum Hock")
    todo.due_marker = "next_session"
    plain = make_protocol_todo(db, block.id, task="Ohne Termin", sort_index=1)

    assignment = SubmissionAssignment(tenant_id=tenant.id, title="Jahresbericht", public_slug="jahresbericht-v2", source_type="manual")
    db.add(assignment)
    db.flush()
    plain.submission_assignment_id = assignment.id
    db.flush()

    item = _item(db, tenant.id, todo)
    assert item.due_session_title == "Hock 15"
    assert item.resolved_due_date == date(2026, 12, 1)
    assert item.submission_title is None

    closing = _item(db, tenant.id, plain)
    assert closing.due_session_title is None
    assert closing.submission_title == "Jahresbericht"


def test_submission_title_of_foreign_tenant_is_not_joined(db):
    tenant = make_tenant(db, "Tenant Eigen v2")
    other = make_tenant(db, "Tenant Fremd v2")
    foreign = SubmissionAssignment(tenant_id=other.id, title="Fremde Abgabe", public_slug="fremd-v2", source_type="manual")
    db.add(foreign)
    db.flush()
    todo = service.create_standalone_todo(db, tenant.id, ProtocolTodoCreate(task="Kein Fremdtitel", todo_status_id=1))
    # Inkonsistenz absichtlich herstellen: der Join darf trotzdem nichts aus dem fremden Mandanten lesen
    todo.submission_assignment_id = foreign.id
    db.flush()

    assert _item(db, tenant.id, todo).submission_title is None
