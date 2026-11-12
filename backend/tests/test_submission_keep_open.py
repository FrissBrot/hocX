"""Abgaben: Pendenz fällig am Ende des Fensters, Option «nach dem Enddatum offen halten» (0173)."""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select

from app.models.entities import ProtocolTodo, SubmissionAssignment
from app.schemas.submission import SubmissionAssignmentCreate, SubmissionAssignmentUpdate, SubmissionLinkCreate
from app.services.submission_link_service import SubmissionLinkService
from app.services.submission_service import SubmissionService
from tests.factories import make_event, make_participant, make_tenant


def test_todo_due_date_is_the_end_of_the_window_and_keep_open_is_stored(db):
    tenant = make_tenant(db, "Abgaben Verein")
    event = make_event(db, tenant.id, title="Sommerlager", event_date=date(2026, 7, 10), event_end_date=date(2026, 7, 18))
    event.tag = "lager"
    event.spezial1_ids = [make_participant(db, tenant.id, display_name="Anna Muster").id]
    db.flush()
    link = SubmissionLinkService().create_link(db, SubmissionLinkCreate(name="Leiter"), tenant_id=tenant.id)
    service = SubmissionService()
    created = service.create_assignment(
        db,
        SubmissionAssignmentCreate(
            title="Lagerberichte", public_slug="lagerberichte", source_type="events", tag_filter="lager",
            offset_days_before=0, offset_days_after=3, keep_open_after_end=True, link_ids=[link.id],
            responsible_participant_source="spezial1_ids",
        ),
        tenant_id=tenant.id,
    )
    assignment = db.scalar(select(SubmissionAssignment).where(SubmissionAssignment.public_id == created.id))
    assert assignment.keep_open_after_end is True and created.keep_open_after_end is True
    [todo] = db.scalars(select(ProtocolTodo).where(ProtocolTodo.submission_assignment_id == assignment.id))
    # Fällig am Ende des Fensters: letzter Lagertag + 3 Tage
    assert todo.due_date == date(2026, 7, 18) + timedelta(days=3)

    service.update_assignment(db, assignment.id, SubmissionAssignmentUpdate(keep_open_after_end=False))
    db.refresh(assignment)
    assert assignment.keep_open_after_end is False
