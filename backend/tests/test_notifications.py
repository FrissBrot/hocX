"""Benachrichtigungen per E-Mail (Migration 0170, app/notifications/)."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.models import Notification, PlatformNotificationSettings, ProtocolTodo, TodoStatus
from app.notifications import dispatch, email_transport, publish
from app.notifications import preferences as notification_preferences
from app.notifications import todos as todo_notifications
from app.schemas.notifications import NotificationPreferenceRead, NotificationPreferencesWrite
from app.schemas.protocol import ProtocolTodoCreate, ProtocolTodoUpdate, ProtocolUpdate
from app.services.notification_settings_service import NotificationSettingsService
from app.services.protocol_service import ProtocolService
from app.services.protocol_todo_service import ProtocolTodoService
from tests.factories import (
    make_app_user,
    make_participant,
    make_protocol,
    make_protocol_element,
    make_protocol_element_block,
    make_protocol_todo,
    make_template,
    make_tenant,
)

TZ = ZoneInfo("Europe/Zurich")


def _status(db, code: str) -> int:
    return db.scalar(select(TodoStatus.id).where(TodoStatus.code == code))


@pytest.fixture
def sent():
    """Fängt den Versand ab statt SMTP."""
    mails: list = []
    email_transport.override_transport(lambda config, email: mails.append(email))
    yield mails
    email_transport.override_transport(None)


def _enable_email(db):
    row = NotificationSettingsService().get_row(db)
    row.email_enabled = True
    row.smtp_host = "smtp.example.com"
    row.email_from_address = "noreply@example.com"
    row.email_link_base_url = "https://app.example.com"
    db.flush()


@pytest.fixture
def club(db):
    tenant = make_tenant(db, "Pfadi Test")
    anna = make_app_user(db, "anna@example.com", tenant_id=tenant.id, first_name="Anna", last_name="A")
    ben = make_app_user(db, "ben@example.com", tenant_id=tenant.id, first_name="Ben", last_name="B")
    offline = make_participant(db, tenant.id, "Ohne Login")
    offline.email = "offline@example.com"
    db.flush()
    return {"tenant": tenant, "anna": anna, "ben": ben, "offline": offline}


def _standalone(db, club, *, assignee="anna", actor=None, due=None) -> ProtocolTodo:
    payload = ProtocolTodoCreate(task="Zelt flicken", assigned_participant_id=club[assignee].public_id, todo_status_id=_status(db, "open"), due_date=due)
    return ProtocolTodoService().create_standalone_todo(db, club["tenant"].id, payload, actor_user_id=actor)


def _pending(db, **filters):
    query = select(Notification).where(Notification.status == "pending")
    for key, value in filters.items():
        query = query.where(getattr(Notification, key) == value)
    return db.scalars(query).all()


def _protocol_todo(db, club, *, status="geplant", task="Lagerplatz reservieren", assignee="anna"):
    template = make_template(db, club["tenant"].id)
    protocol = make_protocol(db, club["tenant"].id, template.id, status=status)
    element = make_protocol_element(db, protocol.id)
    block = make_protocol_element_block(db, element.id, {}, element_type_code="todo")
    todo = make_protocol_todo(db, block.id, task=task)
    todo.assigned_participant_id = club[assignee].id
    db.flush()
    return protocol, todo


def test_publish_is_idempotent_per_dedupe_key(db, club):
    args = dict(kind="todo.assigned", tenant_id=club["tenant"].id, recipient_ids=[club["anna"].id], subject_id=1, dedupe="1")
    assert publish(db, **args) == 1
    assert publish(db, **args) == 0


def test_standalone_todo_notifies_assignee_but_not_the_actor(db, club):
    todo = _standalone(db, club, actor=club["ben"].id)
    rows = _pending(db, subject_id=todo.id)
    assert [(r.kind, r.recipient_id) for r in rows] == [("todo.assigned", club["anna"].id)]
    assert rows[0].deliver_after > datetime.now(TZ)  # Bündelungsfenster
    own = _standalone(db, club, actor=club["anna"].id)
    assert _pending(db, subject_id=own.id) == []


def test_protocol_todos_wait_for_the_protocol_to_close(db, club):
    protocol, todo = _protocol_todo(db, club)
    done = make_protocol_todo(db, todo.protocol_element_block_id, task="Erledigt", sort_index=1)
    done.assigned_participant_id = club["ben"].id
    done.todo_status_id = _status(db, "done")
    db.flush()
    ProtocolTodoService().update_todo(db, todo.id, ProtocolTodoUpdate(task="Lagerplatz buchen"))
    assert _pending(db, subject_id=todo.id) == []

    service = ProtocolService()
    for status in ("vorbereitet", "durchgeführt"):
        service.update_protocol(db, protocol.id, ProtocolUpdate(status=status), notify_todos=True)
    assert _pending(db) == []
    service.update_protocol(db, protocol.id, ProtocolUpdate(status="abgeschlossen"), actor_user_id=club["ben"].id, notify_todos=True)
    assert [(r.subject_id, r.recipient_id) for r in _pending(db)] == [(todo.id, club["anna"].id)]


def test_closing_without_notify_flag_sends_nothing(db, club):
    """Word-Import schliesst historische Protokolle ohne notify_todos ab."""
    protocol, _todo = _protocol_todo(db, club)
    ProtocolService().update_protocol(db, protocol.id, ProtocolUpdate(status="abgeschlossen"))
    assert _pending(db) == []


def test_new_assignee_of_released_todo_is_notified_once(db, club):
    todo = _standalone(db, club)
    ProtocolTodoService().update_todo(
        db, todo.id, ProtocolTodoUpdate(assigned_participant_ids=[club["anna"].public_id, club["ben"].public_id]), actor_user_id=club["anna"].id,
    )
    assert sorted(r.recipient_id for r in _pending(db, subject_id=todo.id)) == sorted([club["anna"].id, club["ben"].id])
    ProtocolTodoService().update_todo(db, todo.id, ProtocolTodoUpdate(assigned_participant_ids=[club["ben"].public_id]))
    ProtocolTodoService().update_todo(db, todo.id, ProtocolTodoUpdate(assigned_participant_ids=[club["anna"].public_id, club["ben"].public_id]))
    assert len(_pending(db, subject_id=todo.id)) == 2


def test_reminders_once_per_todo_and_only_after_seven(db, club):
    today = date(2026, 11, 11)
    soon = _standalone(db, club, due=today + timedelta(days=3))
    late = _standalone(db, club, due=today - timedelta(days=1))
    other = _standalone(db, club, due=today + timedelta(days=2))
    _protocol_open, in_open_protocol = _protocol_todo(db, club)
    in_open_protocol.due_date = today + timedelta(days=3)
    db.flush()
    early = datetime(2026, 11, 11, 6, 30, tzinfo=TZ)
    assert todo_notifications.scan_reminders(db, now=early) == {"due_soon": 0, "overdue": 0}
    morning = datetime(2026, 11, 11, 7, 5, tzinfo=TZ)
    assert todo_notifications.scan_reminders(db, now=morning) == {"due_soon": 1, "overdue": 1}
    assert todo_notifications.scan_reminders(db, now=morning) == {"due_soon": 0, "overdue": 0}
    kinds = {(r.subject_id, r.kind) for r in _pending(db) if r.kind != "todo.assigned"}
    assert kinds == {(soon.id, "todo.due_soon"), (late.id, "todo.overdue")}
    assert other.id not in {r.subject_id for r in _pending(db) if r.kind != "todo.assigned"}


def _make_due(db):
    db.execute(Notification.__table__.update().values(deliver_after=datetime.now(TZ) - timedelta(minutes=1)))


def test_dispatch_bundles_per_person_and_respects_settings(db, club, sent):
    first = _standalone(db, club)
    second = _standalone(db, club)
    _standalone(db, club, assignee="offline")
    _make_due(db)
    assert dispatch.run(db).get("expired", 0) == 0 and sent == []  # Versand aus: nichts geht raus

    _enable_email(db)
    result = dispatch.run(db)
    assert len(sent) == 1 and sent[0].to == "anna@example.com"
    assert "Pfadi Test" in sent[0].subject and sent[0].text.count("Zelt flicken") == 2
    assert "https://app.example.com/todos" in sent[0].text
    assert result.get("sent") == 1 and result.get("skipped") == 1
    statuses = {r.subject_id: r.status for r in db.scalars(select(Notification))}
    assert statuses[first.id] == statuses[second.id] == "sent"
    offline_row = db.scalar(select(Notification).where(Notification.recipient_id == club["offline"].id))
    assert offline_row.status == "skipped" and offline_row.skip_reason == "no_login"


def test_dispatch_to_person_without_login_only_when_admin_allowed(db, club, sent):
    club["offline"].notify_without_login = True
    _standalone(db, club, assignee="offline")
    _enable_email(db)
    _make_due(db)
    dispatch.run(db)
    assert [mail.to for mail in sent] == ["offline@example.com"]
    assert "/todos" not in sent[0].text  # ohne Login kein Link in die App


def test_dispatch_skips_obsolete_items_and_disabled_categories(db, club, sent):
    done_before_send = _standalone(db, club)
    ProtocolTodoService().update_todo(db, done_before_send.id, ProtocolTodoUpdate(todo_status_id=_status(db, "done")))
    notification_preferences.write(
        db, club["ben"].id, club["tenant"].id, NotificationPreferencesWrite(preferences=[NotificationPreferenceRead(category="todo_new", enabled=False)]),
    )
    _standalone(db, club, assignee="ben")
    _enable_email(db)
    _make_due(db)
    dispatch.run(db)
    assert sent == []
    reasons = {r.recipient_id: r.skip_reason for r in db.scalars(select(Notification))}
    assert reasons == {club["anna"].id: "obsolete", club["ben"].id: "preference_off"}


def test_dispatch_retries_on_smtp_error(db, club):
    def fail(config, email):
        raise email_transport.EmailError("SMTPServerDisconnected: weg")

    email_transport.override_transport(fail)
    try:
        _standalone(db, club)
        _enable_email(db)
        _make_due(db)
        assert dispatch.run(db).get("failed") == 1
        row = db.scalar(select(Notification))
        assert row.status == "pending" and row.attempts == 1 and row.deliver_after > datetime.now(TZ)
        assert db.get(PlatformNotificationSettings, 1).email_last_error.startswith("SMTPServerDisconnected")
    finally:
        email_transport.override_transport(None)


def test_preferences_default_on_and_scoped_to_own_account(db, club):
    other_tenant = make_tenant(db, "Anderer Verein")
    result = notification_preferences.read(db, club["anna"].id, club["tenant"].id)
    assert {p.category: p.enabled for p in result.preferences} == {"todo_new": True, "todo_reminders": True, "todo_submissions": True, "exports": True}
    notification_preferences.write(
        db, club["anna"].id, club["tenant"].id,
        NotificationPreferencesWrite(preferences=[NotificationPreferenceRead(category="todo_reminders", enabled=False)]),
    )
    assert {p.category: p.enabled for p in notification_preferences.read(db, club["anna"].id, club["tenant"].id).preferences}["todo_reminders"] is False
    # Unter einem anderen Mandanten gibt es diese Einstellung nicht
    assert all(p.enabled for p in notification_preferences.read(db, club["anna"].id, other_tenant.id).preferences)


def test_email_settings_keep_password_secret_and_validate(db, sent):
    from app.schemas.admin import EmailSettingsWrite

    service = NotificationSettingsService()
    with pytest.raises(ValueError):
        service.update_email(db, EmailSettingsWrite(email_enabled=True, smtp_host="smtp.example.com"))
    result = service.update_email(db, EmailSettingsWrite(
        email_enabled=True, smtp_host="smtp.example.com", smtp_username="hocx", smtp_password="geheim-123", email_from_address="noreply@example.com",
    ))
    assert result.smtp_password_set and "geheim" not in result.model_dump_json()
    assert db.get(PlatformNotificationSettings, 1).smtp_password_encrypted != "geheim-123"
    assert email_transport.load_config(db).password == "geheim-123"
    service.send_test_email(db, "admin@example.com")
    assert [mail.to for mail in sent] == ["admin@example.com"]
    with pytest.raises(ValueError):
        service.send_test_email(db, "keine-adresse")


def test_unexpected_error_counts_as_attempt_and_subject_is_one_line(db, club, sent):
    club["tenant"].name = "Pfadi\r\nBcc: boese@example.com"
    _standalone(db, club)
    _enable_email(db)
    _make_due(db)
    dispatch.run(db)
    assert len(sent) == 1 and "\n" not in sent[0].subject and "\r" not in sent[0].subject

    def boom(config, email):
        raise RuntimeError("kaputt")

    email_transport.override_transport(boom)
    try:
        _standalone(db, club, assignee="ben")
        _make_due(db)
        assert dispatch.run(db).get("error") == 1
        row = db.scalar(select(Notification).where(Notification.recipient_id == club["ben"].id))
        assert row.status == "pending" and row.attempts == 1
    finally:
        email_transport.override_transport(None)
