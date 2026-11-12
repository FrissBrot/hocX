"""Von Hand geschlossene Elemente zählen als erledigt (Entscheid 2026-11-12): ohne Datei wird die
Aufgabe abgebrochen (keine Busse), mit Datei bleibt sie erledigt, Wiederöffnen öffnet sie wieder."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.models import ProtocolTodo, StoredFile, SubmissionAssignment, SubmissionUpload, SubmissionUploadFile, TodoStatus
from app.schemas.submission import SubmissionAssignmentCreate, SubmissionLinkCreate
from app.services.submission_link_service import SubmissionLinkService
from app.services.submission_service import SubmissionService
from tests.factories import make_event, make_participant, make_tenant

service = SubmissionService()


@pytest.fixture
def box(db):
    tenant = make_tenant(db)
    other = make_tenant(db)
    anna = make_participant(db, tenant.id, display_name="Anna Muster")
    event = make_event(db, tenant.id, title="Badetag")
    event.tag = "lager"
    event.spezial1_ids = [anna.id]
    db.flush()
    link = SubmissionLinkService().create_link(db, SubmissionLinkCreate(name="Leiter"), tenant_id=tenant.id)
    created = service.create_assignment(
        db,
        SubmissionAssignmentCreate(
            title="Berichte", public_slug="berichte", source_type="events", tag_filter="lager",
            offset_days_before=7, offset_days_after=7, link_ids=[link.id], responsible_participant_source="spezial1_ids",
        ),
        tenant_id=tenant.id,
    )
    assignment = db.scalar(select(SubmissionAssignment).where(SubmissionAssignment.public_id == created.id))
    [todo] = db.scalars(select(ProtocolTodo).where(ProtocolTodo.submission_assignment_id == assignment.id))
    return {"tenant": tenant, "other": other, "event": event, "assignment": assignment, "todo": todo}


def _status_id(db, code: str) -> int:
    return db.scalar(select(TodoStatus.id).where(TodoStatus.code == code))


def _code(db, todo) -> str:
    db.expire(todo)
    return db.scalar(select(TodoStatus.code).where(TodoStatus.id == todo.todo_status_id))


def test_closing_without_file_cancels_the_task_and_reopening_opens_it(db, box):
    todo, assignment = box["todo"], box["assignment"]
    element = service.close_element(db, assignment, todo.element_ref)
    assert element.status == "closed"
    assert _code(db, todo) == "cancelled" and todo.completed_at is not None

    counts = service.summaries(db, [assignment])[assignment.id]
    assert counts["closed"] == 1 and counts["submitted"] == 0

    service.reopen_element(db, assignment, todo.element_ref)
    assert _code(db, todo) == "open" and todo.completed_at is None
    assert service.summaries(db, [assignment])[assignment.id]["closed"] == 0


def test_closing_after_a_submission_keeps_the_task_done(db, box):
    """Geschlossen mit geprüfter Datei bleibt erledigt; «abgebrochen» wird beim Abgleich erledigt."""
    todo, assignment = box["todo"], box["assignment"]
    upload = SubmissionUpload(assignment_id=assignment.id, event_id=box["event"].id, status="submitted", submitted_at=datetime.now(UTC))
    db.add(upload)
    db.flush()
    stored = StoredFile(tenant_id=box["tenant"].id, original_name="a.jpg", mime_type="image/jpeg", storage_path="uploads/a.jpg")
    db.add(stored)
    db.flush()
    db.add(SubmissionUploadFile(upload_id=upload.id, stored_file_id=stored.id, sort_index=0))
    db.flush()
    assert _code(db, todo) == "done"  # Trigger (geprüfte Datei)
    service.close_element(db, assignment, todo.element_ref)
    assert _code(db, todo) == "done"

    db.execute(ProtocolTodo.__table__.update().where(ProtocolTodo.id == todo.id).values(todo_status_id=_status_id(db, "cancelled")))
    db.expire_all()
    service.sync_submission_todos(db, assignment)
    assert _code(db, todo) == "done"  # sauber → erledigt, auch aus «abgebrochen»


def test_todo_sync_cancels_tasks_of_elements_closed_before_the_change(db, box):
    todo, assignment = box["todo"], box["assignment"]
    # Stand vor dieser Änderung: geschlossen, Aufgabe noch offen
    db.add(SubmissionUpload(assignment_id=assignment.id, event_id=box["event"].id, status="closed"))
    db.flush()
    assert _code(db, todo) == "open"
    service.sync_submission_todos(db, assignment)
    assert _code(db, todo) == "cancelled"


def test_closed_count_is_per_assignment(db, box):
    todo, assignment = box["todo"], box["assignment"]
    service.close_element(db, assignment, todo.element_ref)
    other_event = make_event(db, box["other"].id, title="Fremd")
    other_event.tag = "lager"
    db.flush()
    assert service.summaries(db, [assignment])[assignment.id]["closed"] == 1
