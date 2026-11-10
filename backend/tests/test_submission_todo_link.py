"""Verknüpfung Termin -> Abgabe -> Pendenz: jede Änderung am Termin kommt in der Pendenz an
(Person, Titel, Tag-Wechsel, Löschen, Tag umbenennen), eingereichte bzw. verknüpfte Dateien
erledigen sie, und der periodische Abgleich holt den Rest nach."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from app.api.routes import events as event_routes
from app.models.entities import (
    GalleryImage,
    ProtocolTodo,
    StoredFile,
    SubmissionAssignment,
    TenantFeature,
    TodoStatus,
)
from app.schemas.event import EventUpdate
from app.schemas.submission import SubmissionAssignmentCreate, SubmissionLinkCreate
from app.services.submission_link_service import SubmissionLinkService
from app.services.submission_service import SubmissionService
from tests.factories import make_current_user, make_event, make_participant, make_tenant

service = SubmissionService()


def _status_id(db, code: str) -> int:
    return db.scalar(select(TodoStatus.id).where(TodoStatus.code == code))


def _setup(db, *, tag: str = "lager"):
    tenant = make_tenant(db)
    anna = make_participant(db, tenant.id, display_name="Anna Muster")
    ben = make_participant(db, tenant.id, display_name="Ben Beispiel")
    event = make_event(db, tenant.id, title="Badetag")
    event.tag = tag
    event.spezial1_ids = [anna.id]
    db.flush()
    link = SubmissionLinkService().create_link(db, SubmissionLinkCreate(name="Leiter"), tenant_id=tenant.id)
    created = service.create_assignment(
        db,
        SubmissionAssignmentCreate(
            title="Berichte", public_slug="berichte", source_type="events", tag_filter=tag,
            link_ids=[link.id], responsible_participant_source="spezial1_ids",
        ),
        tenant_id=tenant.id,
    )
    assignment = db.scalar(select(SubmissionAssignment).where(SubmissionAssignment.public_id == created.id))
    user = make_current_user(tenant.id)
    return tenant, user, assignment, event, anna, ben


def _todos(db, assignment) -> list[ProtocolTodo]:
    db.expire_all()
    return list(db.scalars(select(ProtocolTodo).where(ProtocolTodo.submission_assignment_id == assignment.id)))


def _patch(db, user, event, **values):
    return event_routes.patch_event(event.public_id, EventUpdate(**values), db=db, user=user)


def test_changing_person_and_title_reaches_the_todo(db):
    tenant, user, assignment, event, anna, ben = _setup(db)
    [todo] = _todos(db, assignment)
    assert todo.assigned_participant_id == anna.id

    _patch(db, user, event, title="Badetag Allmend", spezial1_ids=[ben.public_id])

    [todo] = _todos(db, assignment)
    assert todo.assigned_participant_id == ben.id
    assert todo.task == "Berichte: Badetag Allmend"


def test_removing_the_person_or_tag_removes_the_open_todo(db):
    tenant, user, assignment, event, anna, ben = _setup(db)
    _patch(db, user, event, spezial1_ids=[])
    assert _todos(db, assignment) == []

    _patch(db, user, event, spezial1_ids=[anna.public_id])
    assert len(_todos(db, assignment)) == 1

    # Tag-Wechsel: die Abgabe des alten Tags verliert das Element
    _patch(db, user, event, tag="anderes")
    assert _todos(db, assignment) == []


def test_deleting_the_event_removes_open_but_keeps_done_todos(db):
    tenant, user, assignment, event, anna, ben = _setup(db)
    other = make_event(db, tenant.id, title="Schneetag")
    other.tag = "lager"
    other.spezial1_ids = [ben.id]
    db.flush()
    service.sync_todos_for_tenant(db, tenant_id=tenant.id)
    done_todo = next(t for t in _todos(db, assignment) if t.assigned_participant_id == ben.id)
    done_todo.todo_status_id = _status_id(db, "done")
    db.commit()

    event_routes.delete_event(event.public_id, db=db, user=user)
    event_routes.delete_event(other.public_id, db=db, user=user)

    assert [t.id for t in _todos(db, assignment)] == [done_todo.id]


def test_renaming_the_tag_keeps_the_assignment_and_todo(db):
    tenant, user, assignment, event, anna, ben = _setup(db)
    [todo] = _todos(db, assignment)

    event_routes.rename_tag(event_routes.RenameTagPayload(old_tag="lager", new_tag="sola"), db=db, user=user)

    db.expire_all()
    assert assignment.tag_filter == "sola"
    assert [t.id for t in _todos(db, assignment)] == [todo.id]


def test_linked_file_completes_the_todo(db):
    """Direkt verknüpfte Dateien (Galerie) zählen als Abgabe, lösen aber keinen Trigger aus."""
    tenant, user, assignment, event, anna, ben = _setup(db)
    [todo] = _todos(db, assignment)
    stored = StoredFile(tenant_id=tenant.id, original_name="a.jpg", mime_type="image/jpeg", storage_path="uploads/a.jpg")
    db.add(stored)
    db.flush()
    db.add(GalleryImage(
        tenant_id=tenant.id, stored_file_id=stored.id, submission_assignment_id=assignment.id,
        submission_element_ref=todo.element_ref,
    ))
    db.commit()

    service.sync_todos_for_tenant(db, tenant_id=tenant.id)

    [todo] = _todos(db, assignment)
    assert todo.todo_status_id == _status_id(db, "done")
    assert todo.completed_at is not None


def test_periodic_sync_only_for_booked_tenants(db):
    tenant, user, assignment, event, anna, ben = _setup(db)
    event.spezial1_ids = [ben.id]  # Änderung ohne Route, z. B. ein künftiger Weg ohne Abgleich
    db.commit()
    feature = db.scalar(select(TenantFeature).where(TenantFeature.tenant_id == tenant.id, TenantFeature.feature_code == "abgabebox"))
    if feature is not None:
        feature.access = "read_only"
        db.commit()
        service.sync_all_todos(db)
        assert _todos(db, assignment)[0].assigned_participant_id == anna.id
        feature.access = "full"
    else:
        db.add(TenantFeature(tenant_id=tenant.id, feature_code="abgabebox", access="full"))
    db.commit()

    result = service.sync_all_todos(db)

    assert result["assignments"] >= 1
    assert _todos(db, assignment)[0].assigned_participant_id == ben.id


def test_submitted_at_is_used_as_completion_time(db):
    from app.models.entities import SubmissionUpload, SubmissionUploadFile

    tenant, user, assignment, event, anna, ben = _setup(db)
    stored = StoredFile(tenant_id=tenant.id, original_name="a.pdf", mime_type="application/pdf", storage_path="uploads/a.pdf")
    db.add(stored)
    submitted_at = datetime(2026, 10, 12, 9, 30, tzinfo=UTC)
    upload = SubmissionUpload(assignment_id=assignment.id, event_id=event.id, status="submitted", submitted_at=submitted_at)
    db.add(upload)
    db.flush()
    db.add(SubmissionUploadFile(upload_id=upload.id, stored_file_id=stored.id, sort_index=0))
    db.commit()

    service.sync_todos_for_tenant(db, tenant_id=tenant.id)

    [todo] = _todos(db, assignment)
    assert todo.todo_status_id == _status_id(db, "done")


def test_several_responsibles_share_one_todo(db):
    from app.services.task_package_service import todo_assignee_ids

    tenant, user, assignment, event, anna, ben = _setup(db)
    _patch(db, user, event, spezial1_ids=[anna.public_id, ben.public_id])

    [todo] = _todos(db, assignment)
    assert todo_assignee_ids(db, todo.id) == [anna.id, ben.id]
    [element] = service.get_assignment_elements(db, assignment)
    assert element.responsible_participant_ids == [anna.public_id, ben.public_id]

    _patch(db, user, event, spezial1_ids=[ben.public_id])
    [todo] = _todos(db, assignment)
    assert todo_assignee_ids(db, todo.id) == [ben.id]
    assert todo.assigned_participant_id == ben.id


def test_files_in_quarantine_do_not_complete_the_todo(db):
    from app.models.entities import SubmissionUpload, SubmissionUploadFile

    tenant, user, assignment, event, anna, ben = _setup(db)
    stored = StoredFile(tenant_id=tenant.id, original_name="a.pdf", mime_type="application/pdf", storage_path="q/a.pdf", scan_status="pending")
    db.add(stored)
    upload = SubmissionUpload(assignment_id=assignment.id, event_id=event.id, status="submitted", submitted_at=datetime.now(UTC))
    db.add(upload)
    db.flush()
    db.add(SubmissionUploadFile(upload_id=upload.id, stored_file_id=stored.id, sort_index=0))
    db.commit()
    open_id = _status_id(db, "open")
    for todo in _todos(db, assignment):
        todo.todo_status_id = open_id  # falls der Datenbank-Trigger schon erledigt hat
    db.commit()

    service.sync_todos_for_tenant(db, tenant_id=tenant.id)
    assert _todos(db, assignment)[0].todo_status_id == open_id

    stored.scan_status = "clean"
    db.commit()
    service.sync_todos_for_tenant(db, tenant_id=tenant.id)
    assert _todos(db, assignment)[0].todo_status_id == _status_id(db, "done")


def test_todo_with_notes_is_cancelled_instead_of_deleted(db):
    tenant, user, assignment, event, anna, ben = _setup(db)
    [todo] = _todos(db, assignment)
    todo.notes = "Fotos liegen bei Anna"
    db.commit()

    _patch(db, user, event, spezial1_ids=[])

    [todo] = _todos(db, assignment)
    assert todo.notes == "Fotos liegen bei Anna"
    assert todo.todo_status_id == _status_id(db, "cancelled")
