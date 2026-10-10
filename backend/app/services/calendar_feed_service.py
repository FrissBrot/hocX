"""Kalender-Abos ("Verknuepfungen"): abonnierbare iCal-Feeds, ueber die Apple Kalender und
Google Kalender die Termine bzw. Todos eines Benutzers nur lesend anzeigen.

Der Token in der Feed-URL ist die Authentifizierung (wie bei share_link_service.py), wird aber
nur als SHA-256-Hash (Nachschlagen) und Fernet-verschluesselt (erneutes Anzeigen in den
Einstellungen) gespeichert. Bei jedem Abruf wird der Benutzer frisch aufgeloest - deaktivierte
Konten, "ueberall abmelden" und Rollen-/Zugriffsaenderungen wirken sofort auf den Feed, und Todos
laufen durch dieselben Listing-Helfer wie GET /todos (eingeschraenkte Leser sehen also auch im
Kalender nur, was sie in hocX sehen).

Alle Eintraege sind ganztaegig: Termine haben in hocX nur ein Datum, Todos ein Faelligkeitsdatum.
Ein eigener, kleiner Serializer statt einer iCal-Bibliothek - es werden nur VEVENTs mit
DATE-Werten erzeugt; Escaping und Zeilenfaltung folgen RFC 5545 (Abschnitte 3.1 und 3.3.11)."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session

from app.core.secret_crypto import decrypt_secret, encrypt_secret
from app.core.security import CurrentUser, build_current_user
from app.models.entities import AppUser, CalendarFeed, Event, Protocol
from app.schemas.protocol import TodoListItem
from app.services.access_service import AccessService
from app.services.protocol_todo_service import ProtocolTodoService

KINDS = ("events", "todos")
TODO_SCOPES = ("mine", "all")
# Todos: gleiche Rollen wie require_reader (GET /todos). Termine: wie die Oberflaeche (Termine-Seite,
# Mobile-Tab und Navigation nur fuer writer/admin) - ein Abo soll keinen neuen Zugang oeffnen.
_ALLOWED_ROLES = {
    "events": frozenset({"writer", "admin"}),
    "todos": frozenset({"reader", "kassier", "writer", "admin"}),
}


def can_subscribe(role: str | None, kind: str) -> bool:
    return role in _ALLOWED_ROLES.get(kind, frozenset())

# 24 Bytes = 192 Bit Entropie, gleiches Mass wie share_link_service.generate_token().
_TOKEN_BYTES = 24
# Zeitfenster des Feeds: haelt die Datei klein (Kalender-Apps laden sie bei jedem Abruf ganz),
# deckt aber den ueblichen Blick zurueck und die Jahresplanung ab.
WINDOW_PAST_DAYS = 180
WINDOW_FUTURE_DAYS = 730
# Obergrenze fuer die Todo-Abfrage - die Listing-Helfer paginieren, ein Feed will alles im Fenster.
_TODO_LIMIT = 5000
# last_accessed_at nur so oft schreiben - Kalender-Apps fragen teils minuetlich.
_ACCESS_WRITE_INTERVAL = timedelta(minutes=10)
_COMPLETED_TODO_CODES = frozenset({"done"})
_SKIPPED_TODO_CODES = frozenset({"cancelled"})

_todo_service = ProtocolTodoService()
_access_service = AccessService()


class CalendarFeedError(ValueError):
    """Erwartete Validierungsfehler (unbekannte Art/Option) - die Route macht daraus einen 422."""


@dataclass(frozen=True)
class FeedSettings:
    calendar_name: str
    todo_scope: str = "mine"
    include_completed: bool = False
    hide_details: bool = False


def generate_token() -> str:
    return secrets.token_urlsafe(_TOKEN_BYTES)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def token_of(feed: CalendarFeed) -> str:
    return decrypt_secret(feed.token_encrypted)


def feed_path(feed: CalendarFeed) -> str:
    return f"/api/public/calendar/{token_of(feed)}.ics"


def _validate(kind: str, settings: FeedSettings) -> FeedSettings:
    if kind not in KINDS:
        raise CalendarFeedError("Unbekannte Kalenderart")
    if settings.todo_scope not in TODO_SCOPES:
        raise CalendarFeedError("Unbekannter Todo-Umfang")
    name = " ".join(settings.calendar_name.split())
    if not name or len(name) > 120:
        raise CalendarFeedError("Kalendername muss zwischen 1 und 120 Zeichen lang sein")
    return FeedSettings(
        calendar_name=name,
        todo_scope=settings.todo_scope,
        include_completed=settings.include_completed,
        hide_details=settings.hide_details,
    )


def list_for_user(db: Session, user_id: int) -> list[CalendarFeed]:
    return list(db.scalars(select(CalendarFeed).where(CalendarFeed.user_id == user_id).order_by(CalendarFeed.kind)).all())


def get_for_user(db: Session, user_id: int, kind: str) -> CalendarFeed | None:
    return db.scalar(select(CalendarFeed).where(CalendarFeed.user_id == user_id, CalendarFeed.kind == kind))


def _assign_new_token(feed: CalendarFeed) -> None:
    token = generate_token()
    feed.token_hash = hash_token(token)
    feed.token_encrypted = encrypt_secret(token)
    feed.token_created_at = datetime.now(UTC)
    feed.last_accessed_at = None


def upsert(db: Session, *, user: CurrentUser, kind: str, settings: FeedSettings) -> tuple[CalendarFeed, bool]:
    """Legt den Feed dieser Art an oder aktualisiert seine Optionen - die URL bleibt dabei gleich,
    damit bestehende Abos weiterlaufen. Gibt (feed, created) zurueck."""
    settings = _validate(kind, settings)
    feed = get_for_user(db, user.user_id, kind)
    created = feed is None
    if feed is None:
        feed = CalendarFeed(tenant_id=user.current_tenant_id, user_id=user.user_id, kind=kind)
        _assign_new_token(feed)
        db.add(feed)
    feed.calendar_name = settings.calendar_name
    feed.todo_scope = settings.todo_scope
    feed.include_completed = settings.include_completed
    feed.hide_details = settings.hide_details
    feed.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(feed)
    return feed, created


def regenerate_token(db: Session, feed: CalendarFeed) -> CalendarFeed:
    """Neue URL - die alte ist ab sofort ungueltig (bestehende Abos muessen neu eingerichtet werden)."""
    _assign_new_token(feed)
    feed.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(feed)
    return feed


def delete(db: Session, feed: CalendarFeed) -> None:
    db.delete(feed)
    db.commit()


def is_token_valid_for(feed: CalendarFeed, app_user: AppUser) -> bool:
    """False, wenn der Benutzer sich nach Ausstellung der URL "ueberall abgemeldet" hat (bzw. das
    Passwort geaendert wurde) - die Einstellungsseite zeigt den Feed dann als ungueltig an."""
    revoked_at = app_user.session_revoke_at
    return revoked_at is None or feed.token_created_at >= revoked_at


def resolve(db: Session, token: str) -> tuple[CalendarFeed, CurrentUser] | None:
    """Feed + frisch aufgebauter CurrentUser des Besitzers, oder None - fuer jeden Grund
    (unbekannt, Konto inaktiv, Mandant gewechselt, Sitzungen widerrufen, Rolle ohne Lesezugriff)
    gleich, damit ein Ratender nichts daraus lernt."""
    if not token or len(token) > 128:
        return None
    feed = db.scalar(select(CalendarFeed).where(CalendarFeed.token_hash == hash_token(token)))
    if feed is None:
        return None
    app_user = db.get(AppUser, feed.user_id)
    if app_user is None or not app_user.is_active or app_user.tenant_id != feed.tenant_id:
        return None
    if not is_token_valid_for(feed, app_user):
        return None
    user = build_current_user(db, app_user)
    if not can_subscribe(user.current_role, feed.kind):
        return None
    return feed, user


def touch(db: Session, feed: CalendarFeed, *, now: datetime | None = None) -> None:
    now = now or datetime.now(UTC)
    if feed.last_accessed_at is not None and now - feed.last_accessed_at < _ACCESS_WRITE_INTERVAL:
        return
    feed.last_accessed_at = now
    db.commit()


# --- iCal-Ausgabe -----------------------------------------------------------------------------


def _escape(value: str) -> str:
    """TEXT-Wert nach RFC 5545 3.3.11; uebrige Steuerzeichen fliegen raus (sie sind in iCal
    nicht erlaubt und brechen sonst einzelne Clients)."""
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = "".join(ch for ch in value if ch == "\n" or ch == "\t" or ord(ch) >= 0x20)
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> str:
    """Zeilen hoechstens 75 Oktette, Fortsetzung mit CRLF + Leerzeichen (RFC 5545 3.1) - nach
    Bytes gezaehlt, ohne ein UTF-8-Zeichen zu zerteilen."""
    parts: list[str] = []
    current = ""
    current_len = 0
    limit = 75
    for ch in line:
        ch_len = len(ch.encode())
        if current_len + ch_len > limit:
            parts.append(current)
            current = ""
            current_len = 0
            limit = 74  # Folgezeilen beginnen mit einem Leerzeichen
        current += ch
        current_len += ch_len
    parts.append(current)
    return "\r\n ".join(parts)


def _date(value: date) -> str:
    return value.strftime("%Y%m%d")


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


@dataclass(frozen=True)
class _Entry:
    uid: str
    start: date
    end_inclusive: date
    summary: str
    updated_at: datetime
    description: str | None = None
    location: str | None = None
    cancelled: bool = False
    transparent: bool = False


def _render_calendar(name: str, entries: list[_Entry]) -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//hocX//Kalender-Abo//DE",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape(name)}",
        # Wunsch an die Clients, stuendlich neu zu laden (Apple beachtet es, Google entscheidet selbst).
        "REFRESH-INTERVAL;VALUE=DURATION:PT1H",
        "X-PUBLISHED-TTL:PT1H",
    ]
    for entry in entries:
        modified = _timestamp(entry.updated_at)
        lines += [
            "BEGIN:VEVENT",
            f"UID:{entry.uid}",
            # Bewusst updated_at statt "jetzt": so ist die Ausgabe bei unveraenderten Daten
            # byte-gleich und der ETag-Abgleich (304) der Route greift.
            f"DTSTAMP:{modified}",
            f"LAST-MODIFIED:{modified}",
            f"DTSTART;VALUE=DATE:{_date(entry.start)}",
            # DTEND ist bei Ganztagesterminen exklusiv - der Tag nach dem letzten Tag.
            f"DTEND;VALUE=DATE:{_date(entry.end_inclusive + timedelta(days=1))}",
            f"SUMMARY:{_escape(entry.summary)}",
        ]
        if entry.description:
            lines.append(f"DESCRIPTION:{_escape(entry.description)}")
        if entry.location:
            lines.append(f"LOCATION:{_escape(entry.location)}")
        lines.append(f"STATUS:{'CANCELLED' if entry.cancelled else 'CONFIRMED'}")
        lines.append(f"TRANSP:{'TRANSPARENT' if entry.transparent else 'OPAQUE'}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "".join(_fold(line) + "\r\n" for line in lines)


def _event_entries(db: Session, feed: CalendarFeed, user: CurrentUser, *, today: date) -> list[_Entry]:
    window_start = today - timedelta(days=WINDOW_PAST_DAYS)
    window_end = today + timedelta(days=WINDOW_FUTURE_DAYS)
    # Gleiche Sichtbarkeit wie EventRepository.list: automatisch erzeugte Sitzungs-Platzhalter erst,
    # wenn tatsaechlich ein Protokoll daran haengt.
    has_protocol = exists().where(Protocol.event_id == Event.id)
    events = db.scalars(
        select(Event)
        .where(
            Event.tenant_id == user.current_tenant_id,
            or_(Event.is_session_marker.is_(False), has_protocol),
            Event.event_date <= window_end,
            or_(Event.event_date >= window_start, Event.event_end_date >= window_start),
        )
        .order_by(Event.event_date, Event.id)
    ).all()
    entries = []
    for event in events:
        end = event.event_end_date if event.event_end_date and event.event_end_date >= event.event_date else event.event_date
        entries.append(
            _Entry(
                uid=f"event-{event.public_id}@hocx",
                start=event.event_date,
                end_inclusive=end,
                summary=event.title,
                updated_at=event.updated_at,
                description=None if feed.hide_details else (event.description or None),
                location=None if feed.hide_details else (event.location or None),
                cancelled=event.is_cancelled,
            )
        )
    return entries


def _visible_todos(db: Session, feed: CalendarFeed, user: CurrentUser) -> list[TodoListItem]:
    """Dieselben Listing-Helfer und dieselbe Rechte-Logik wie GET /todos bzw. /todos/my."""
    tenant_id = user.current_tenant_id
    if feed.todo_scope == "mine":
        return _todo_service.list_todos_for_user(db, tenant_id, user.user_id, limit=_TODO_LIMIT)
    if _access_service.is_restricted_reader(db, user):
        protocol_ids = _access_service.repository.list_protocol_ids(db, user_id=user.user_id, tenant_id=tenant_id)
        return _todo_service.list_todos_for_protocols_or_assigned(db, tenant_id, protocol_ids, user.user_id, limit=_TODO_LIMIT)
    return _todo_service.list_todos_for_tenant(db, tenant_id, limit=_TODO_LIMIT)


def _todo_description(todo: TodoListItem) -> str | None:
    lines = []
    if todo.protocol_number or todo.protocol_title:
        lines.append(" · ".join(part for part in (todo.protocol_number, todo.protocol_title) if part))
    if todo.assigned_participant_name:
        lines.append(todo.assigned_participant_name)
    if todo.resolved_due_label:
        lines.append(todo.resolved_due_label)
    if todo.reference_link:
        lines.append(todo.reference_link)
    return "\n".join(lines) or None


def _todo_entries(db: Session, feed: CalendarFeed, user: CurrentUser, *, today: date) -> list[_Entry]:
    window_start = today - timedelta(days=WINDOW_PAST_DAYS)
    window_end = today + timedelta(days=WINDOW_FUTURE_DAYS)
    entries = []
    for todo in _visible_todos(db, feed, user):
        due = todo.resolved_due_date
        # Todos ohne aufloesbares Datum (z. B. "naechste Sitzung" ohne geplanten Termin) haben im
        # Kalender keinen Platz.
        if due is None or due < window_start or due > window_end:
            continue
        code = todo.todo_status_code or ""
        if code in _SKIPPED_TODO_CODES:
            continue
        completed = code in _COMPLETED_TODO_CODES
        if completed and not feed.include_completed:
            continue
        entries.append(
            _Entry(
                uid=f"todo-{todo.id}@hocx",
                start=due,
                end_inclusive=due,
                # Sprachneutrale Markierung statt uebersetztem Praefix - das Backend kennt keine UI-Texte.
                summary=f"{'✓' if completed else '☐'} {todo.task}",
                updated_at=todo.updated_at,
                description=None if feed.hide_details else _todo_description(todo),
                # Todos blockieren keine Zeit in der Verfuegbarkeitsansicht.
                transparent=True,
            )
        )
    entries.sort(key=lambda entry: (entry.start, entry.uid))
    return entries


def render(db: Session, feed: CalendarFeed, user: CurrentUser, *, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    today = now.date()
    if feed.kind == "events":
        entries = _event_entries(db, feed, user, today=today)
    else:
        entries = _todo_entries(db, feed, user, today=today)
    return _render_calendar(feed.calendar_name, entries)
