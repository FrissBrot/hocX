"""Nebenläufigkeit beim Einrichten des Kalender-Abos.

upsert legt den Feed an, wenn es noch keinen gibt. Zwei gleichzeitige Anfragen derselben Person
(Doppelklick, zwei Tabs) sehen beide «noch keiner» und legen beide an: die zweite scheiterte an
uq_calendar_feed_user_kind mit einem unbehandelten IntegrityError (500, Fehlerprotokoll).
Erwartet: die zweite übernimmt den Feed der ersten (gleiche URL, ihre Optionen).
"""

from __future__ import annotations

import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from fastapi import Response
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.api.routes import calendar_feeds as routes
from app.core.db import engine
from app.models import Tenant
from app.models.entities import AppUser, CalendarFeed
from app.schemas.calendar_feed import CalendarFeedUpsert
from tests.factories import make_app_user, make_current_user, make_tenant


def _wait_until_blocked(timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    with engine.connect() as probe:
        while time.monotonic() < deadline:
            if probe.scalar(text("SELECT count(*) FROM pg_locks WHERE NOT granted")):
                return True
            time.sleep(0.05)
    return False


def test_parallel_first_subscription_creates_one_feed():
    with Session(engine) as setup:
        tenant = make_tenant(setup, "Kalender parallel")
        app_user = make_app_user(setup, email=f"{uuid.uuid4().hex[:8]}@example.com", tenant_id=tenant.id, role_code="writer")
        setup.commit()
        tenant_id, user_id = tenant.id, app_user.id
    user = make_current_user(tenant_id, role="writer", user_id=user_id)

    def subscribe(db: Session, name: str):
        return routes.upsert_calendar_feed("events", CalendarFeedUpsert(calendar_name=name), Response(), db, user)

    def second_request():
        with Session(engine) as db:
            try:
                return subscribe(db, "Zweiter Tab")
            except Exception as exc:  # Befund festhalten
                return type(exc).__name__

    pool = ThreadPoolExecutor(1)
    first = Session(engine)
    try:
        original_commit = first.commit
        first.commit = first.flush  # erste Anfrage: Feed geschrieben, Commit noch nicht durch
        try:
            first_read = subscribe(first, "Erster Tab")
        finally:
            first.commit = original_commit
        future = pool.submit(second_request)
        blocked = _wait_until_blocked()
        first.commit()
        second = future.result(timeout=30)
    finally:
        first.rollback()
        first.close()
        pool.shutdown(wait=True)

    try:
        assert blocked, "zweite Anfrage wartet nicht auf die erste"
        assert not isinstance(second, str), f"zweite gleichzeitige Anfrage scheitert mit {second}"
        assert second.path == first_read.path
        with Session(engine) as check:
            feeds = check.scalars(select(CalendarFeed).where(CalendarFeed.user_id == user_id)).all()
        assert [feed.calendar_name for feed in feeds] == ["Zweiter Tab"]
    finally:
        with Session(engine) as cleanup:
            cleanup.execute(delete(CalendarFeed).where(CalendarFeed.user_id == user_id))
            cleanup.execute(delete(AppUser).where(AppUser.id == user_id))
            cleanup.execute(delete(Tenant).where(Tenant.id == tenant_id))
            cleanup.commit()
