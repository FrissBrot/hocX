"""Migration 0164: eine Einreichung erledigt ihre Abgabe-Pendenz wieder (Trigger vergleicht über
die öffentliche ID), das Wiedereröffnen eines Elements nicht, und bereits eingereichte Elemente
werden einmalig nachgeholt."""
from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select, update

from app.models.entities import ProtocolTodo, StoredFile, SubmissionAssignment, SubmissionUpload, SubmissionUploadFile
from app.schemas.submission import SubmissionAssignmentCreate, SubmissionLinkCreate
from app.services.submission_link_service import SubmissionLinkService
from app.services.submission_service import SubmissionService
from tests.factories import make_event, make_participant, make_tenant

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DONE = 3


@pytest.fixture
def migration(db, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "migration_0164", BACKEND_ROOT / "alembic/versions/0164_submission_todo_public_ref.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.op, "get_bind", lambda: db.connection(), raising=False)
    monkeypatch.setattr(module.op, "execute", lambda sql: db.connection().exec_driver_sql(sql), raising=False)
    return module


def _assignment_with_todo(db):
    tenant = make_tenant(db)
    participant = make_participant(db, tenant.id, display_name="Anna Muster")
    event = make_event(db, tenant.id, title="Badetag")
    event.tag = "lager"
    event.spezial1_ids = [participant.id]
    db.flush()
    link = SubmissionLinkService().create_link(db, SubmissionLinkCreate(name="Leiter"), tenant_id=tenant.id)
    created = SubmissionService().create_assignment(
        db,
        SubmissionAssignmentCreate(
            title="Berichte", public_slug="berichte", source_type="events", tag_filter="lager",
            offset_days_before=7, offset_days_after=7, link_ids=[link.id], responsible_participant_source="spezial1_ids",
        ),
        tenant_id=tenant.id,
    )
    assignment = db.scalar(select(SubmissionAssignment).where(SubmissionAssignment.public_id == created.id))
    [todo] = db.scalars(select(ProtocolTodo).where(ProtocolTodo.submission_assignment_id == assignment.id))
    assert todo.element_ref == f"event-{event.public_id}"
    return tenant, assignment, event, todo


def _upload(db, tenant, assignment, event, *, submitted_at, with_file=True):
    upload = SubmissionUpload(assignment_id=assignment.id, event_id=event.id, status="submitted", submitted_at=submitted_at)
    db.add(upload)
    db.flush()
    if with_file:
        stored = StoredFile(tenant_id=tenant.id, original_name="a.jpg", mime_type="image/jpeg", storage_path="uploads/a.jpg")
        db.add(stored)
        db.flush()
        db.add(SubmissionUploadFile(upload_id=upload.id, stored_file_id=stored.id, sort_index=0))
        db.flush()
    return upload


def _reopen_like_old_trigger(db, todo) -> None:
    """Stand vor 0164: der alte Trigger liess die Pendenz offen. Die Test-Datenbank hat den
    neuen Trigger schon, deshalb hier zurücksetzen."""
    db.execute(update(ProtocolTodo).where(ProtocolTodo.id == todo.id).values(todo_status_id=1, completed_at=None))
    db.expire(todo)


def _status(db, todo) -> int:
    db.expire(todo)
    return todo.todo_status_id


def test_submission_completes_todo_but_reopen_does_not(db, migration):
    tenant, assignment, event, todo = _assignment_with_todo(db)
    migration.upgrade()

    _upload(db, tenant, assignment, event, submitted_at=None, with_file=False)  # reopen_element
    assert _status(db, todo) != DONE

    _upload(db, tenant, assignment, event, submitted_at=datetime.now(UTC))
    assert _status(db, todo) == DONE


def test_backfill_completes_todos_of_already_submitted_elements(db, migration):
    tenant, assignment, event, todo = _assignment_with_todo(db)
    submitted_at = datetime(2026, 10, 12, 9, 30, tzinfo=UTC)
    _upload(db, tenant, assignment, event, submitted_at=submitted_at)
    _reopen_like_old_trigger(db, todo)  # der alte Trigger fand die Pendenz nicht

    migration.upgrade()

    assert _status(db, todo) == DONE
    assert todo.completed_at == submitted_at


def test_backfill_ignores_elements_without_files(db, migration):
    tenant, assignment, event, todo = _assignment_with_todo(db)
    _upload(db, tenant, assignment, event, submitted_at=datetime.now(UTC), with_file=False)
    _reopen_like_old_trigger(db, todo)

    migration.upgrade()

    assert _status(db, todo) != DONE


def test_upload_log_refs_become_public(db, migration):
    from app.models.entities import SubmissionUploadLog

    tenant, assignment, event, todo = _assignment_with_todo(db)
    log = SubmissionUploadLog(assignment_id=assignment.id, element_ref=f"event-{event.id}", status="rescan_clean")
    db.add(log)
    db.flush()

    migration.upgrade()

    db.expire(log)
    assert log.element_ref == f"event-{event.public_id}"


def test_rescan_writes_public_element_refs(db):
    from app.repositories.submission_repository import SubmissionRepository

    tenant, assignment, event, todo = _assignment_with_todo(db)
    stored = StoredFile(tenant_id=tenant.id, original_name="a.jpg", mime_type="image/jpeg", storage_path="uploads/a.jpg", scan_status="pending")
    db.add(stored)
    upload = SubmissionUpload(assignment_id=assignment.id, event_id=event.id, status="submitted", submitted_at=datetime.now(UTC))
    db.add(upload)
    db.flush()
    db.add(SubmissionUploadFile(upload_id=upload.id, stored_file_id=stored.id, sort_index=0))
    db.flush()

    [(_file, element_ref)] = SubmissionRepository().list_pending_files_for_assignment(db, assignment_id=assignment.id)

    assert element_ref == f"event-{event.public_id}"
