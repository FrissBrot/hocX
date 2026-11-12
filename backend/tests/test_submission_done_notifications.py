"""Abgabe eingegangen: schliesst eine Einreichung in der Abgabebox die Abgabe-Aufgabe (Trigger
trg_sync_todo_status), bekommen die Verantwortlichen eine Mail (todo.submission_done)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.models import Notification, ProtocolTodo, SubmissionAssignment, SubmissionUpload
from app.notifications import dispatch, email_transport
from app.notifications import preferences as notification_preferences
from app.notifications import todos as todo_notifications
from app.schemas.notifications import NotificationPreferenceRead, NotificationPreferencesWrite
from app.schemas.submission import SubmissionAssignmentCreate, SubmissionLinkCreate
from app.services.notification_settings_service import NotificationSettingsService
from app.services.submission_link_service import SubmissionLinkService
from app.services.submission_service import SubmissionService
from tests.factories import make_app_user, make_event, make_tenant

DONE = 3


@pytest.fixture
def sent():
    mails: list = []
    email_transport.override_transport(lambda config, email: mails.append(email))
    yield mails
    email_transport.override_transport(None)


@pytest.fixture
def box(db):
    tenant = make_tenant(db, "Pfadi Test")
    anna = make_app_user(db, "anna@example.com", tenant_id=tenant.id, first_name="Anna", last_name="A")
    ben = make_app_user(db, "ben@example.com", tenant_id=tenant.id, first_name="Ben", last_name="B")
    event = make_event(db, tenant.id, title="Badetag")
    event.tag = "lager"
    event.spezial1_ids = [anna.id, ben.id]
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
    # «Neue Aufgabe»-Mails aus dem Anlegen interessieren hier nicht
    db.execute(Notification.__table__.delete())
    return {"tenant": tenant, "anna": anna, "ben": ben, "event": event, "assignment": assignment, "todo": todo}


def _submit(db, box, *, submitted_at=None):
    db.add(SubmissionUpload(
        assignment_id=box["assignment"].id, event_id=box["event"].id, status="submitted",
        submitted_at=submitted_at or datetime.now(UTC),
    ))
    db.flush()
    db.expire(box["todo"])


def _done_rows(db):
    return db.scalars(select(Notification).where(Notification.kind == "todo.submission_done").order_by(Notification.id)).all()


def _enable_email(db):
    row = NotificationSettingsService().get_row(db)
    row.email_enabled = True
    row.smtp_host = "smtp.example.com"
    row.email_from_address = "noreply@example.com"
    row.email_link_base_url = "https://app.example.com"
    db.flush()


def _make_due(db):
    db.execute(Notification.__table__.update().values(deliver_after=datetime.now(UTC) - timedelta(minutes=1)))


def test_submission_through_the_box_notifies_all_assignees_once(db, box):
    _submit(db, box)
    assert box["todo"].todo_status_id == DONE  # der Trigger hat geschlossen

    assert todo_notifications.scan_submission_done(db) == 2
    assert {row.recipient_id for row in _done_rows(db)} == {box["anna"].id, box["ben"].id}
    assert todo_notifications.scan_submission_done(db) == 0  # nichts doppelt


def test_closing_by_hand_sends_no_submission_mail(db, box):
    db.execute(update(ProtocolTodo).where(ProtocolTodo.id == box["todo"].id).values(todo_status_id=DONE, completed_at=datetime.now(UTC)))
    assert todo_notifications.scan_submission_done(db) == 0


def test_old_completions_are_not_picked_up(db, box):
    _submit(db, box)
    assert todo_notifications.scan_submission_done(db, now=datetime.now(UTC) + timedelta(days=2)) == 0


def test_dispatch_sends_the_mail_and_respects_the_setting(db, box, sent):
    notification_preferences.write(
        db, box["ben"].id, box["tenant"].id,
        NotificationPreferencesWrite(preferences=[NotificationPreferenceRead(category="todo_submissions", enabled=False)]),
    )
    _submit(db, box)
    _enable_email(db)
    dispatch.run(db)  # legt die Benachrichtigungen an (Bündelungsfenster läuft noch)
    assert sent == []
    _make_due(db)
    dispatch.run(db)
    assert [mail.to for mail in sent] == ["anna@example.com"]
    assert "Abgabe eingegangen" in sent[0].subject
    assert "Berichte: " in sent[0].text and "abgegeben" in sent[0].text
    reasons = {row.recipient_id: (row.status, row.skip_reason) for row in _done_rows(db)}
    assert reasons[box["ben"].id] == ("skipped", "preference_off")


def test_reopened_task_drops_the_pending_mail_and_resubmission_sends_a_new_one(db, box, sent):
    _submit(db, box)
    todo_notifications.scan_submission_done(db)
    # Element wieder geöffnet (Trigger: status reopened) und erneut abgegeben
    db.add(SubmissionUpload(assignment_id=box["assignment"].id, event_id=box["event"].id, status="reopened"))
    db.flush()
    db.execute(update(ProtocolTodo).where(ProtocolTodo.id == box["todo"].id).values(
        todo_status_id=DONE, completed_at=datetime.now(UTC) + timedelta(minutes=1),
    ))
    assert todo_notifications.scan_submission_done(db) == 2  # neuer Abschluss, neue Mail
    _enable_email(db)
    _make_due(db)
    dispatch.run(db)
    # je Person eine Mail mit nur dem aktuellen Abschluss; der alte Eintrag ist überholt
    assert sorted(mail.to for mail in sent) == ["anna@example.com", "ben@example.com"]
    assert all(mail.text.count("Berichte: ") == 1 for mail in sent)
    assert sorted(row.status for row in _done_rows(db)) == ["sent", "sent", "skipped", "skipped"]
