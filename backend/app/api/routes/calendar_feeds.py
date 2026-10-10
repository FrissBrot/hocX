"""Kalender-Abos ("Verknuepfungen", siehe calendar_feed_service.py): Verwaltung der eigenen Feeds
(authentifiziert, immer nur fuer den eingeloggten Benutzer selbst) und der oeffentliche
.ics-Abruf, bei dem der Token in der URL die Authentifizierung ist - Apple Kalender und Google
Kalender koennen keine Cookies/Logins mitschicken."""

from __future__ import annotations

import hashlib
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.rate_limit import enforce_rate_limit
from app.core.security import CurrentUser, get_current_user, require_reader
from app.models.entities import AppUser, CalendarFeed
from app.schemas.calendar_feed import CalendarFeedRead, CalendarFeedUpsert
from app.services import calendar_feed_service
from app.services.audit_service import AuditService

router = APIRouter()
audit = AuditService()

FeedKind = Literal["events", "todos"]


def _read(feed: CalendarFeed, app_user: AppUser | None, role: str) -> CalendarFeedRead:
    # Gleiche Bedingungen wie calendar_feed_service.resolve - "invalid" heisst: der Abruf liefert 404.
    valid = (
        app_user is not None
        and calendar_feed_service.is_token_valid_for(feed, app_user)
        and calendar_feed_service.can_subscribe(role, feed.kind)
    )
    return CalendarFeedRead(
        kind=feed.kind,
        calendar_name=feed.calendar_name,
        path=calendar_feed_service.feed_path(feed),
        todo_scope=feed.todo_scope,
        include_completed=feed.include_completed,
        hide_details=feed.hide_details,
        created_at=feed.created_at,
        token_created_at=feed.token_created_at,
        last_accessed_at=feed.last_accessed_at,
        status="active" if valid else "invalid",
    )


def _own_feed_or_404(db: Session, user: CurrentUser, kind: str) -> CalendarFeed:
    feed = calendar_feed_service.get_for_user(db, user.user_id, kind)
    if feed is None:
        raise HTTPException(status_code=404, detail="Kalender-Abo nicht gefunden")
    return feed


@router.get("/calendar-feeds", response_model=list[CalendarFeedRead])
def list_calendar_feeds(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_reader(user)
    app_user = db.get(AppUser, user.user_id)
    return [_read(feed, app_user, user.current_role) for feed in calendar_feed_service.list_for_user(db, user.user_id)]


@router.put("/calendar-feeds/{kind}", response_model=CalendarFeedRead)
def upsert_calendar_feed(
    kind: FeedKind,
    payload: CalendarFeedUpsert,
    response: Response,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_reader(user)
    if not calendar_feed_service.can_subscribe(user.current_role, kind):
        raise HTTPException(status_code=403, detail="Kein Zugriff auf diese Kalenderart")
    try:
        feed, created = calendar_feed_service.upsert(
            db,
            user=user,
            kind=kind,
            settings=calendar_feed_service.FeedSettings(
                calendar_name=payload.calendar_name,
                todo_scope=payload.todo_scope,
                include_completed=payload.include_completed,
                hide_details=payload.hide_details,
            ),
        )
    except calendar_feed_service.CalendarFeedError as exc:
        # Validierung laeuft vor jedem Schreibzugriff - nichts zurueckzurollen.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if created:
        response.status_code = 201
        audit.log(db, action="calendar_feed.created", actor=user, entity_type="calendar_feed", entity_id=feed.id, details={"kind": kind})
    return _read(feed, db.get(AppUser, user.user_id), user.current_role)


@router.post("/calendar-feeds/{kind}/regenerate", response_model=CalendarFeedRead)
def regenerate_calendar_feed(kind: FeedKind, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_reader(user)
    feed = calendar_feed_service.regenerate_token(db, _own_feed_or_404(db, user, kind))
    audit.log(db, action="calendar_feed.regenerated", actor=user, entity_type="calendar_feed", entity_id=feed.id, details={"kind": kind})
    return _read(feed, db.get(AppUser, user.user_id), user.current_role)


@router.delete("/calendar-feeds/{kind}", status_code=204)
def delete_calendar_feed(kind: FeedKind, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_reader(user)
    feed = _own_feed_or_404(db, user, kind)
    feed_id = feed.id
    calendar_feed_service.delete(db, feed)
    audit.log(db, action="calendar_feed.deleted", actor=user, entity_type="calendar_feed", entity_id=feed_id, details={"kind": kind})
    return Response(status_code=204)


# --- Oeffentlicher Abruf ------------------------------------------------------------------------


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@router.get("/public/calendar/{token}.ics")
def get_calendar_feed(token: str, request: Request, db: Session = Depends(get_db)):
    resolved = calendar_feed_service.resolve(db, token)
    if resolved is None:
        # Nur Fehlversuche zaehlen pro IP: Google ruft alle Abos von wenigen gemeinsamen IPs ab,
        # ein IP-Limit fuer gueltige Abrufe wuerde dort grosse Mandanten treffen.
        enforce_rate_limit(f"calendar-feed:miss:{_client_ip(request)}", limit=20, period_seconds=60)
        # Gleiche Antwort fuer unbekannt, widerrufen, deaktiviert - ein Ratender lernt nichts.
        raise HTTPException(status_code=404, detail="Kalender nicht gefunden")
    feed, user = resolved
    enforce_rate_limit(f"calendar-feed:token:{feed.id}", limit=30, period_seconds=60)

    body = calendar_feed_service.render(db, feed, user)
    calendar_feed_service.touch(db, feed)
    etag = '"' + hashlib.sha256(body.encode()).hexdigest()[:32] + '"'
    headers = {
        "ETag": etag,
        "Cache-Control": "private, max-age=300",
        "X-Robots-Tag": "noindex, nofollow",
        "Content-Disposition": f'inline; filename="hocx-{feed.kind}.ics"',
    }
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=body, media_type="text/calendar; charset=utf-8", headers=headers)
