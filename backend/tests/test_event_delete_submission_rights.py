"""Termin löschen löscht per Kaskade die Abgabe-Einreichungen des Termins (und vorher deren
Dateien, event_service.delete_event). Das ist Löschen von Abgabe-Daten: wer sie nicht verwalten
darf (eigene Rolle mit meetings.edit ohne submissions.manage), darf sie auch nicht über den
Termin mitlöschen - analog zu Protokoll löschen/Anwesenheitsbussen."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.api.routes import events as events_route
from app.models import Event
from app.models.entities import SubmissionAssignment, SubmissionUpload
from tests.factories import make_current_user, make_event, make_tenant


def _event_with_submission(db):
    tenant = make_tenant(db)
    event = make_event(db, tenant.id, title="Badetag")
    event.tag = "lager"
    assignment = SubmissionAssignment(tenant_id=tenant.id, title="Berichte", public_slug="berichte-rechte", source_type="events", tag_filter="lager")
    db.add(assignment)
    db.flush()
    db.add(SubmissionUpload(assignment_id=assignment.id, event_id=event.id, status="submitted", submitted_at=datetime.now(UTC)))
    db.flush()
    return tenant, event


def _uploads(db, event_id: int) -> int:
    return db.scalar(select(func.count()).select_from(SubmissionUpload).where(SubmissionUpload.event_id == event_id))


def test_deleting_an_event_with_submissions_needs_submissions_manage(db):
    tenant, event = _event_with_submission(db)
    planner = make_current_user(tenant.id, role="writer", permissions=frozenset({"meetings.read", "meetings.read_drafts", "meetings.edit"}))

    with pytest.raises(HTTPException) as exc_info:
        events_route.delete_event(event.public_id, db=db, user=planner)
    assert exc_info.value.status_code == 403
    assert db.get(Event, event.id) is not None
    assert _uploads(db, event.id) == 1


def test_writer_with_submissions_manage_may_delete_the_event_and_its_submissions(db):
    tenant, event = _event_with_submission(db)
    event_id = event.id
    writer = make_current_user(tenant.id, role="writer")

    events_route.delete_event(event.public_id, db=db, user=writer)
    assert _uploads(db, event_id) == 0


def test_events_without_submissions_need_only_meetings_edit(db):
    tenant = make_tenant(db)
    event = make_event(db, tenant.id, title="Hock")
    planner = make_current_user(tenant.id, role="writer", permissions=frozenset({"meetings.read", "meetings.read_drafts", "meetings.edit"}))

    events_route.delete_event(event.public_id, db=db, user=planner)
    assert db.scalar(select(Event.id).where(Event.id == event.id)) is None
