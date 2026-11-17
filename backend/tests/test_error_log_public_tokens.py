"""Fehlerprotokoll ohne Zugangstoken: Kalender-Abo (Todos/Termine) und Freigabe-Links tragen ihren
Token im Pfad (Kalender-Apps können keine Header senden). Wirft die Route einen unerwarteten
Fehler, landete der Pfad samt Token unverändert in system_error_log.request_path - jeder mit
Zugriff aufs Fehlerprotokoll konnte danach die Pendenzen der Person abonnieren (SECURITY-RULES 5.1:
keine Geheimnisse in Logs)."""
from __future__ import annotations

import uuid

from fastapi import Response
from sqlalchemy import select
from starlette.requests import Request

from app.api.routes import calendar_feeds as routes
from app.core import error_log
from app.core.error_log import record_system_error
from app.models import SystemErrorLog
from app.schemas.calendar_feed import CalendarFeedUpsert
from tests.factories import make_app_user, make_current_user, make_tenant


def _request(path: str) -> Request:
    return Request({"type": "http", "method": "GET", "path": path, "headers": [], "query_string": b""})


def _todo_feed_token(db, tenant_id: int) -> str:
    app_user = make_app_user(db, email=f"{uuid.uuid4().hex[:8]}@example.com", tenant_id=tenant_id, role_code="writer")
    user = make_current_user(tenant_id, role="writer", user_id=app_user.id)
    read = routes.upsert_calendar_feed("todos", CalendarFeedUpsert(calendar_name="Pendenzen", todo_scope="all"), Response(), db, user)
    return read.path.removeprefix("/api/public/calendar/").removesuffix(".ics")


def test_calendar_feed_token_never_lands_in_the_error_log(db):
    tenant = make_tenant(db, "Tokenlog")
    token = _todo_feed_token(db, tenant.id)

    record_system_error(db, exc=RuntimeError("Feed kaputt"), request=_request(f"/api/public/calendar/{token}.ics"), tenant_id=tenant.id, status_code=500)

    entry = db.scalars(select(SystemErrorLog).where(SystemErrorLog.tenant_id == tenant.id)).one()
    assert token not in (entry.request_path or "")
    # Diagnose bleibt möglich: welche Route betroffen war, ist weiter sichtbar.
    assert entry.request_path == "/api/public/calendar/<token>.ics"


def test_share_link_tokens_are_masked_in_every_share_route():
    token = "Zz" + uuid.uuid4().hex
    file_id = str(uuid.uuid4())

    assert error_log.redact_path(f"/api/public/share/{token}") == "/api/public/share/<token>"
    assert error_log.redact_path(f"/api/public/share/{token}/download") == "/api/public/share/<token>/download"
    assert error_log.redact_path(f"/api/public/share/{token}/files/{file_id}/view") == f"/api/public/share/<token>/files/{file_id}/view"


def test_ordinary_paths_stay_unchanged():
    path = f"/api/protocols/{uuid.uuid4()}/todos"
    assert error_log.redact_path(path) == path
    assert error_log.redact_path("/api/public/submission-access/upload") == "/api/public/submission-access/upload"
    assert error_log.redact_path(None) is None
