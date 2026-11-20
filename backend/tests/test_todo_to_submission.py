"""«Als Abgabe einsammeln»: Einzelabgabe aus einer Pendenz (POST /protocol-todos/{id}/create-submission).

- Erfolg: Abgabe mit Standard-Element (Stichtag = Fälligkeit, Verantwortliche = Zugewiesene), die
  Pendenz selbst wird die Pendenz des Elements (keine zweite), Notizen/Tags/Protokoll-Bezug bleiben,
  eine geprüfte Einreichung erledigt die Pendenz wie bei normalen Abgaben.
- Slug eindeutig im Mandanten, schon verknüpft/erledigt/ohne Verantwortliche abgelehnt.
- Rechte: submissions.manage nötig (403), fremder Mandant 404, abgeschlossenes Protokoll 409.
- Löschen der Abgabe löscht eine Protokoll-Pendenz nicht mit.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, text

from app.api.routes import todos as todo_routes
from app.models import ProtocolTodo, SubmissionAssignment, SubmissionManualElement, TodoStatus
from app.services import deletion_service, submission_link_service
from app.services.task_package_service import set_todo_assignees, todo_assignee_ids
from tests.factories import (
    make_current_user,
    make_participant,
    make_protocol,
    make_protocol_element,
    make_protocol_element_block,
    make_protocol_todo,
    make_template,
    make_tenant,
)
from tests.test_submission_manual_elements import _upload


@pytest.fixture
def org(db):
    tenant = make_tenant(db, "Pfadi Pendenz")
    other = make_tenant(db, "Fremdverein")
    anna = make_participant(db, tenant.id, display_name="Anna Muster")
    ben = make_participant(db, tenant.id, display_name="Ben Beispiel")
    submission_link_service.create_default_link(db, tenant.id, commit=False)
    return {
        "tenant": tenant, "other": other, "anna": anna, "ben": ben,
        "user": make_current_user(tenant.id, role="admin"),
        "other_user": make_current_user(other.id, role="admin"),
    }


def _status_id(db, code: str) -> int:
    return db.scalar(select(TodoStatus.id).where(TodoStatus.code == code))


def _standalone_todo(db, org, task="Bankvollmacht einreichen", *, assignees=None, due=None, status="open") -> ProtocolTodo:
    todo = ProtocolTodo(
        tenant_id=org["tenant"].id, protocol_element_block_id=None, sort_index=0, task=task,
        todo_status_id=_status_id(db, status), due_date=due, tags=["Finanzen"], notes="Original beilegen",
    )
    db.add(todo)
    db.flush()
    people = assignees if assignees is not None else [org["anna"], org["ben"]]
    if people:
        set_todo_assignees(db, todo, [person.id for person in people])
    return todo


def _protocol_todo(db, org, *, status="geplant") -> ProtocolTodo:
    template = make_template(db, org["tenant"].id)
    protocol = make_protocol(db, org["tenant"].id, template.id, status=status, track_changes_enabled=False)
    element = make_protocol_element(db, protocol.id)
    block = make_protocol_element_block(db, element.id, {}, element_type_code="todo")
    todo = make_protocol_todo(db, block.id, task="Lagerfotos sammeln")
    todo.tags = ["Lager"]
    set_todo_assignees(db, todo, [org["anna"].id])
    db.flush()
    return todo


def _convert(db, org, todo, user=None):
    return todo_routes.create_submission_from_todo(todo.public_id, db=db, user=user or org["user"])


def _todos_of(db, assignment_id: int) -> list[ProtocolTodo]:
    db.expire_all()
    return list(db.scalars(select(ProtocolTodo).where(ProtocolTodo.submission_assignment_id == assignment_id)))


def test_creates_single_submission_and_takes_over_the_todo(db, org):
    due = date.today() + timedelta(days=10)
    todo = _standalone_todo(db, org, due=due)
    todos_before = db.scalar(select(func.count()).select_from(ProtocolTodo).where(ProtocolTodo.tenant_id == org["tenant"].id))

    result = _convert(db, org, todo)

    assert result.title == "Bankvollmacht einreichen" and result.public_slug == "bankvollmacht-einreichen"
    assert result.element_url and result.element_url.endswith("/bankvollmacht-einreichen/manual")
    assignment = db.scalar(select(SubmissionAssignment).where(SubmissionAssignment.public_id == result.assignment_id))
    assert assignment.tenant_id == org["tenant"].id and assignment.source_type == "manual"
    assert (assignment.max_files_per_element, assignment.max_file_size_mb, assignment.auto_close, assignment.owner_access) == (5, 20, "never", "manage")
    assert assignment.keep_open_after_end is False
    [element] = db.scalars(select(SubmissionManualElement).where(SubmissionManualElement.assignment_id == assignment.id))
    assert (element.name, element.window_end, element.is_default) == ("Bankvollmacht einreichen", due, True)
    assert element.responsible_participant_ids == [org["anna"].id, org["ben"].id]

    # Keine zweite Pendenz: die bestehende ist die des Elements
    [linked] = _todos_of(db, assignment.id)
    assert linked.id == todo.id and linked.element_ref == "manual"
    assert db.scalar(select(func.count()).select_from(ProtocolTodo).where(ProtocolTodo.tenant_id == org["tenant"].id)) == todos_before
    assert linked.reference_link == result.element_url
    assert (linked.task, linked.due_date, linked.tags, linked.notes) == ("Bankvollmacht einreichen", due, ["Finanzen"], "Original beilegen")
    assert todo_assignee_ids(db, linked.id) == [org["anna"].id, org["ben"].id]
    assert linked.todo_status_id == _status_id(db, "open")
    assert result.todo.submission_assignment_id == assignment.public_id

    details = db.scalar(text(
        "SELECT details_json FROM audit_log WHERE action = 'submission_assignment.created' AND entity_id = :id"
    ), {"id": assignment.id})
    assert details is not None and details["origin"] == "todo" and details["todo_id"] == str(todo.public_id)

    # Geprüfte Einreichung erledigt die Pendenz wie bei jeder Abgabe (Trigger)
    _upload(db, org["tenant"].id, assignment)
    db.expire_all()
    assert db.get(ProtocolTodo, todo.id).todo_status_id == _status_id(db, "done")


def test_overdue_todo_stays_open(db, org):
    todo = _standalone_todo(db, org, due=date.today() - timedelta(days=3))
    result = _convert(db, org, todo)
    assignment = db.scalar(select(SubmissionAssignment).where(SubmissionAssignment.public_id == result.assignment_id))
    assert assignment.keep_open_after_end is True
    db.expire_all()
    assert db.get(ProtocolTodo, todo.id).todo_status_id == _status_id(db, "open")


def test_slug_collision_gets_a_suffix(db, org):
    first = _convert(db, org, _standalone_todo(db, org, task="Fotos!"))
    second = _convert(db, org, _standalone_todo(db, org, task="Fotos"))
    third = _convert(db, org, _standalone_todo(db, org, task="fotos"))
    assert (first.public_slug, second.public_slug, third.public_slug) == ("fotos", "fotos-2", "fotos-3")


def _expect(db, org, todo, status_code: int, code: str | None = None, user=None):
    with pytest.raises(HTTPException) as excinfo:
        _convert(db, org, todo, user=user)
    assert excinfo.value.status_code == status_code
    if code is not None:
        assert excinfo.value.detail["code"] == code


def test_rejects_linked_closed_and_unassigned_todos(db, org):
    todo = _standalone_todo(db, org)
    _convert(db, org, todo)
    count = db.scalar(select(func.count()).select_from(SubmissionAssignment).where(SubmissionAssignment.tenant_id == org["tenant"].id))
    _expect(db, org, todo, 409, "todo_already_submission")
    _expect(db, org, _standalone_todo(db, org, task="Erledigt", status="done"), 409, "todo_closed")
    _expect(db, org, _standalone_todo(db, org, task="Niemand", assignees=[]), 400, "todo_without_assignee")
    assert db.scalar(select(func.count()).select_from(SubmissionAssignment).where(SubmissionAssignment.tenant_id == org["tenant"].id)) == count


def test_needs_submissions_manage(db, org):
    todo = _standalone_todo(db, org)
    editor = make_current_user(org["tenant"].id, permissions=frozenset({"meetings.read", "meetings.edit"}))
    _expect(db, org, todo, 403, user=editor)
    # Ohne gebuchte Abgabebox ebenfalls 403
    no_feature = make_current_user(org["tenant"].id, role="admin", features=frozenset())
    _expect(db, org, todo, 403, user=no_feature)
    db.expire_all()
    assert db.get(ProtocolTodo, todo.id).submission_assignment_id is None


def test_foreign_tenant_and_unknown_todo_are_404(db, org):
    todo = _standalone_todo(db, org)
    _expect(db, org, todo, 404, user=org["other_user"])
    with pytest.raises(HTTPException) as unknown:
        todo_routes.create_submission_from_todo(uuid.uuid4(), db=db, user=org["user"])
    assert unknown.value.status_code == 404
    db.expire_all()
    assert db.get(ProtocolTodo, todo.id).submission_assignment_id is None


def test_protocol_todo_keeps_its_protocol_and_survives_assignment_deletion(db, org):
    todo = _protocol_todo(db, org)
    block_id = todo.protocol_element_block_id
    result = _convert(db, org, todo)
    assignment = db.scalar(select(SubmissionAssignment).where(SubmissionAssignment.public_id == result.assignment_id))
    [linked] = _todos_of(db, assignment.id)
    assert (linked.id, linked.protocol_element_block_id, linked.tags) == (todo.id, block_id, ["Lager"])

    # Verantwortliche entfernt: die Protokoll-Pendenz wird nicht gelöscht, nur abgebrochen
    element = db.scalar(select(SubmissionManualElement).where(SubmissionManualElement.assignment_id == assignment.id))
    element.responsible_participant_ids = []
    db.flush()
    from app.services.submission_service import SubmissionService

    SubmissionService().sync_submission_todos(db, assignment)
    db.expire_all()
    assert db.get(ProtocolTodo, todo.id).todo_status_id == _status_id(db, "cancelled")

    # Abgabe löschen: die Pendenz bleibt im Protokoll, nur der Bezug fällt weg
    deletion_service.delete_assignment(db, db.get(SubmissionAssignment, assignment.id), delete_file_ids=None, actor_user_id=None)
    db.expire_all()
    kept = db.get(ProtocolTodo, todo.id)
    assert kept is not None and kept.submission_assignment_id is None and kept.element_ref is None
    assert kept.protocol_element_block_id == block_id


def test_closed_protocol_is_rejected(db, org):
    todo = _protocol_todo(db, org, status="abgeschlossen")
    _expect(db, org, todo, 409, "protocol_closed")
    db.expire_all()
    assert db.get(ProtocolTodo, todo.id).submission_assignment_id is None
