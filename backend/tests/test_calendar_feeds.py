"""Kalender-Abos ("Verknuepfungen"): Verwaltung (calendar_feeds.py, eigene Feeds) und oeffentlicher
.ics-Abruf per Token - Routen werden wie in test_share_link_routes.py direkt aufgerufen."""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi import HTTPException, Response
from sqlalchemy import select

from app.api.routes import calendar_feeds as routes
from app.models.entities import CalendarFeed, ProtocolTodo, TodoStatus
from app.schemas.calendar_feed import CalendarFeedUpsert
from app.services import calendar_feed_service
from tests.factories import make_app_user, make_current_user, make_event, make_participant, make_tenant, role_id_by_code


class _FakeClient:
    def __init__(self, host: str) -> None:
        self.host = host


class _FakeRequest:
    """Duck-typed fastapi.Request - die Route liest nur .headers.get(...) und .client.host."""

    def __init__(self, headers: dict[str, str] | None = None) -> None:
        self.client = _FakeClient(f"198.51.100.{uuid.uuid4().hex[:6]}")
        self.headers = headers or {}


TODAY = datetime.now(UTC).date()


def _user(db, tenant_id: int, role: str = "writer", email: str | None = None):
    app_user = make_app_user(db, email=email or f"{uuid.uuid4().hex[:8]}@example.com", tenant_id=tenant_id, role_code=role)
    return app_user, make_current_user(tenant_id, role=role, user_id=app_user.id)


def _enable(db, user, kind: str = "events", **options):
    return routes.upsert_calendar_feed(kind, CalendarFeedUpsert(calendar_name=f"hocX {kind}", **options), Response(), db, user)


def _token(read) -> str:
    return read.path.removeprefix("/api/public/calendar/").removesuffix(".ics")


def _fetch(db, token: str, headers: dict[str, str] | None = None) -> Response:
    return routes.get_calendar_feed(token, _FakeRequest(headers), db)


def _ics(db, token: str) -> str:
    response = _fetch(db, token)
    assert response.status_code == 200
    assert response.media_type.startswith("text/calendar")
    return response.body.decode()


def _status_id(db, code: str) -> int:
    return db.scalar(select(TodoStatus.id).where(TodoStatus.code == code))


def _todo(db, tenant_id: int, task: str, *, due: date | None, status: str = "open", assigned_user_id: int | None = None) -> ProtocolTodo:
    todo = ProtocolTodo(
        tenant_id=tenant_id,
        task=task,
        todo_status_id=_status_id(db, status),
        due_date=due,
        assigned_user_id=assigned_user_id,
        sort_index=0,
    )
    db.add(todo)
    db.flush()
    return todo


# --- iCal-Serializer -------------------------------------------------------------------------


def test_escape_handles_rfc5545_special_characters():
    assert calendar_feed_service._escape("a,b;c\\d\nzeile\r\nzwei\x07") == "a\\,b\\;c\\\\d\\nzeile\\nzwei"


def test_fold_keeps_lines_within_75_octets_without_splitting_utf8():
    line = "SUMMARY:" + "ä" * 100
    folded = calendar_feed_service._fold(line)
    parts = folded.split("\r\n")
    assert all(len(part.encode()) <= 75 for part in parts)
    assert all(part.startswith(" ") for part in parts[1:])
    assert "".join(part[1:] if i else part for i, part in enumerate(parts)) == line


# --- Verwaltung ------------------------------------------------------------------------------


def test_upsert_creates_once_and_keeps_the_url_when_options_change(db):
    tenant = make_tenant(db)
    _, user = _user(db, tenant.id)

    created = _enable(db, user, "todos")
    updated = _enable(db, user, "todos", todo_scope="all", hide_details=True)

    assert created.path == updated.path
    assert updated.todo_scope == "all" and updated.hide_details is True
    assert updated.status == "active"
    assert [feed.kind for feed in routes.list_calendar_feeds(db, user)] == ["todos"]


def test_token_is_stored_only_as_hash_and_encrypted_copy(db):
    tenant = make_tenant(db)
    _, user = _user(db, tenant.id)
    token = _token(_enable(db, user))

    feed = db.scalar(select(CalendarFeed).where(CalendarFeed.user_id == user.user_id))
    assert feed.token_hash == calendar_feed_service.hash_token(token)
    assert token not in feed.token_encrypted


def test_regenerate_invalidates_the_old_url(db):
    tenant = make_tenant(db)
    _, user = _user(db, tenant.id)
    old = _token(_enable(db, user))

    new = _token(routes.regenerate_calendar_feed("events", db, user))

    assert new != old
    with pytest.raises(HTTPException) as exc_info:
        _fetch(db, old)
    assert exc_info.value.status_code == 404
    assert _fetch(db, new).status_code == 200


def test_delete_removes_the_feed_and_its_url(db):
    tenant = make_tenant(db)
    _, user = _user(db, tenant.id)
    token = _token(_enable(db, user))

    routes.delete_calendar_feed("events", db, user)

    assert routes.list_calendar_feeds(db, user) == []
    with pytest.raises(HTTPException) as exc_info:
        _fetch(db, token)
    assert exc_info.value.status_code == 404
    with pytest.raises(HTTPException) as exc_info:
        routes.delete_calendar_feed("events", db, user)
    assert exc_info.value.status_code == 404


def test_feeds_are_per_user_never_shared_with_colleagues(db):
    tenant = make_tenant(db)
    _, owner = _user(db, tenant.id)
    _, colleague = _user(db, tenant.id)
    _enable(db, owner)

    assert routes.list_calendar_feeds(db, colleague) == []
    with pytest.raises(HTTPException) as exc_info:
        routes.regenerate_calendar_feed("events", db, colleague)
    assert exc_info.value.status_code == 404


def test_blank_calendar_name_is_rejected(db):
    tenant = make_tenant(db)
    _, user = _user(db, tenant.id)
    with pytest.raises(HTTPException) as exc_info:
        routes.upsert_calendar_feed("events", CalendarFeedUpsert(calendar_name="   "), Response(), db, user)
    assert exc_info.value.status_code == 422


# --- Oeffentlicher Abruf: Zugriff ------------------------------------------------------------


def test_unknown_token_is_404(db):
    with pytest.raises(HTTPException) as exc_info:
        _fetch(db, "gibt-es-nicht")
    assert exc_info.value.status_code == 404


def test_deactivated_user_loses_the_feed(db):
    tenant = make_tenant(db)
    app_user, user = _user(db, tenant.id)
    token = _token(_enable(db, user))

    app_user.is_active = False
    db.flush()

    with pytest.raises(HTTPException) as exc_info:
        _fetch(db, token)
    assert exc_info.value.status_code == 404


def test_revoking_all_sessions_invalidates_older_urls_until_regenerated(db):
    tenant = make_tenant(db)
    app_user, user = _user(db, tenant.id)
    token = _token(_enable(db, user))

    app_user.session_revoke_at = datetime.now(UTC) + timedelta(seconds=1)
    db.flush()

    with pytest.raises(HTTPException):
        _fetch(db, token)
    assert routes.list_calendar_feeds(db, user)[0].status == "invalid"

    feed = db.scalar(select(CalendarFeed).where(CalendarFeed.user_id == app_user.id))
    feed.token_created_at = app_user.session_revoke_at + timedelta(seconds=1)
    db.flush()
    assert _fetch(db, token).status_code == 200


def test_unchanged_feed_answers_304_for_matching_etag(db):
    tenant = make_tenant(db)
    _, user = _user(db, tenant.id)
    token = _token(_enable(db, user))
    make_event(db, tenant.id, title="Hock", event_date=TODAY)

    first = _fetch(db, token)
    second = _fetch(db, token, {"if-none-match": first.headers["etag"]})

    assert second.status_code == 304
    assert second.body == b""


def test_fetch_records_last_access(db):
    tenant = make_tenant(db)
    _, user = _user(db, tenant.id)
    token = _token(_enable(db, user))

    _fetch(db, token)

    assert routes.list_calendar_feeds(db, user)[0].last_accessed_at is not None


# --- Oeffentlicher Abruf: Inhalt Termine ------------------------------------------------------


def test_events_feed_contains_own_tenant_events_as_all_day_entries(db):
    tenant = make_tenant(db, "Pfadi Test")
    other = make_tenant(db)
    _, user = _user(db, tenant.id)
    token = _token(_enable(db, user))
    camp = make_event(db, tenant.id, title="Sommerlager, Teil 1", event_date=TODAY, event_end_date=TODAY + timedelta(days=6))
    camp.location = "Zeltplatz; Wiese"
    camp.description = "Mitbringen:\nSchlafsack"
    make_event(db, tenant.id, title="Abgesagt", event_date=TODAY + timedelta(days=10), is_cancelled=True)
    make_event(db, other.id, title="Fremder Termin", event_date=TODAY)
    make_event(db, tenant.id, title="Uralt", event_date=TODAY - timedelta(days=calendar_feed_service.WINDOW_PAST_DAYS + 5))
    db.flush()

    ics = _ics(db, token)

    assert ics.startswith("BEGIN:VCALENDAR\r\n") and ics.endswith("END:VCALENDAR\r\n")
    assert "X-WR-CALNAME:hocX events" in ics
    assert f"UID:event-{camp.public_id}@hocx" in ics
    assert "SUMMARY:Sommerlager\\, Teil 1" in ics
    assert f"DTSTART;VALUE=DATE:{TODAY:%Y%m%d}" in ics
    # DTEND ist exklusiv: Tag nach dem letzten Lagertag.
    assert f"DTEND;VALUE=DATE:{TODAY + timedelta(days=7):%Y%m%d}" in ics
    assert "LOCATION:Zeltplatz\\; Wiese" in ics
    assert "DESCRIPTION:Mitbringen:\\nSchlafsack" in ics
    assert "STATUS:CANCELLED" in ics
    assert "Fremder Termin" not in ics
    assert "Uralt" not in ics


def test_hide_details_drops_description_and_location(db):
    tenant = make_tenant(db)
    _, user = _user(db, tenant.id)
    token = _token(_enable(db, user, hide_details=True))
    event = make_event(db, tenant.id, title="Leitersitzung", event_date=TODAY)
    event.location = "Pfadiheim"
    event.description = "Namen von Teilnehmenden"
    db.flush()

    ics = _ics(db, token)

    assert "SUMMARY:Leitersitzung" in ics
    assert "LOCATION" not in ics
    assert "DESCRIPTION" not in ics


# --- Oeffentlicher Abruf: Inhalt Todos --------------------------------------------------------


def test_my_todos_feed_lists_only_assigned_open_todos_with_a_due_date(db):
    tenant = make_tenant(db)
    app_user, user = _user(db, tenant.id)
    colleague, _ = _user(db, tenant.id)
    token = _token(_enable(db, user, "todos"))
    mine = _todo(db, tenant.id, "Material bestellen", due=TODAY + timedelta(days=3), assigned_user_id=app_user.id)
    _todo(db, tenant.id, "Fremdes Todo", due=TODAY, assigned_user_id=colleague.id)
    _todo(db, tenant.id, "Ohne Datum", due=None, assigned_user_id=app_user.id)
    _todo(db, tenant.id, "Erledigt", due=TODAY, status="done", assigned_user_id=app_user.id)
    _todo(db, tenant.id, "Abgebrochen", due=TODAY, status="cancelled", assigned_user_id=app_user.id)

    ics = _ics(db, token)

    assert f"UID:todo-{mine.public_id}@hocx" in ics
    assert "SUMMARY:☐ Material bestellen" in ics
    assert "TRANSP:TRANSPARENT" in ics
    for hidden in ("Fremdes Todo", "Ohne Datum", "Erledigt", "Abgebrochen"):
        assert hidden not in ics


def test_include_completed_shows_done_todos_with_a_check_mark(db):
    tenant = make_tenant(db)
    app_user, user = _user(db, tenant.id)
    token = _token(_enable(db, user, "todos", include_completed=True))
    _todo(db, tenant.id, "Erledigt", due=TODAY, status="done", assigned_user_id=app_user.id)
    _todo(db, tenant.id, "Abgebrochen", due=TODAY, status="cancelled", assigned_user_id=app_user.id)

    ics = _ics(db, token)

    assert "SUMMARY:✓ Erledigt" in ics
    assert "Abgebrochen" not in ics


def test_all_todos_feed_lists_tenant_todos_for_writers(db):
    tenant = make_tenant(db)
    other = make_tenant(db)
    _, user = _user(db, tenant.id)
    colleague, _ = _user(db, tenant.id)
    token = _token(_enable(db, user, "todos", todo_scope="all"))
    _todo(db, tenant.id, "Todo der Kollegin", due=TODAY, assigned_user_id=colleague.id)
    _todo(db, other.id, "Todo anderer Mandant", due=TODAY)

    ics = _ics(db, token)

    assert "Todo der Kollegin" in ics
    assert "Todo anderer Mandant" not in ics


def test_all_todos_feed_respects_restricted_reader_scope(db):
    """Teilnehmer-Konten (eingeschraenkte Leser) sehen auch mit "alle Todos" nur, was GET /todos
    ihnen zeigt - hier: nur direkt Zugewiesenes."""
    tenant = make_tenant(db)
    app_user, user = _user(db, tenant.id, role="reader")
    app_user.external_identity_json = {"source": "participant_auto"}
    participant = make_participant(db, tenant.id, "Kim")
    participant.app_user_id = app_user.id
    colleague, _ = _user(db, tenant.id)
    db.flush()
    token = _token(_enable(db, user, "todos", todo_scope="all"))
    _todo(db, tenant.id, "Fuer Kim", due=TODAY, assigned_user_id=app_user.id)
    _todo(db, tenant.id, "Interna Leitung", due=TODAY, assigned_user_id=colleague.id)

    ics = _ics(db, token)

    assert "Fuer Kim" in ics
    assert "Interna Leitung" not in ics


def test_readers_may_subscribe_to_todos_but_not_to_events(db):
    """Termine sind in der Oberflaeche nur fuer writer/admin sichtbar - das Abo oeffnet keinen
    zusaetzlichen Zugang."""
    tenant = make_tenant(db)
    _, reader = _user(db, tenant.id, role="reader")

    with pytest.raises(HTTPException) as exc_info:
        _enable(db, reader, "events")
    assert exc_info.value.status_code == 403
    assert _enable(db, reader, "todos").status == "active"


def test_events_feed_stops_when_the_owner_is_downgraded_to_reader(db):
    tenant = make_tenant(db)
    app_user, user = _user(db, tenant.id, role="writer")
    token = _token(_enable(db, user, "events"))

    app_user.role_id = role_id_by_code(db, "reader")
    db.flush()

    with pytest.raises(HTTPException) as exc_info:
        _fetch(db, token)
    assert exc_info.value.status_code == 404
    reader = make_current_user(tenant.id, role="reader", user_id=app_user.id)
    assert routes.list_calendar_feeds(db, reader)[0].status == "invalid"
