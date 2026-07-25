"""Persists backend errors for the platform-admin panel's error log (system_error_log).

Two call sites:
- Explicit: route handlers that already catch a specific exception (SQLAlchemyError etc.)
  and convert it to a curated HTTPException call `record_system_error` themselves, with the
  tenant/actor they already know from their own request context.
- Implicit safety net: the global exception handlers in main.py catch anything a route
  didn't handle itself, do a best-effort extraction of tenant/actor from the session
  cookie, and call `record_system_error` before returning a generic response.

Recording a system error must never itself raise - a bug in the logging path can't be
allowed to replace or mask the original error being handled.
"""

from __future__ import annotations

import logging
import traceback as traceback_module

from fastapi import Request
from sqlalchemy.orm import Session

from app.models import AppUser, PlatformAdmin, SystemErrorLog

logger = logging.getLogger(__name__)

_MAX_MESSAGE_LENGTH = 4000
_MAX_TRACEBACK_LENGTH = 20000


def record_system_error(
    db: Session,
    *,
    exc: Exception,
    request: Request | None = None,
    tenant_id: int | None = None,
    actor_email: str | None = None,
    status_code: int | None = None,
    source: str = "backend",
) -> None:
    try:
        entry = SystemErrorLog(
            source=source,
            tenant_id=tenant_id,
            actor_email=actor_email,
            request_method=request.method if request is not None else None,
            request_path=request.url.path if request is not None else None,
            status_code=status_code,
            error_type=type(exc).__name__,
            error_message=str(exc)[:_MAX_MESSAGE_LENGTH],
            traceback="".join(traceback_module.format_exception(type(exc), exc, exc.__traceback__))[:_MAX_TRACEBACK_LENGTH],
        )
        db.add(entry)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to persist system_error_log entry (original error: %s: %s)", type(exc).__name__, exc)


def best_effort_actor_from_request(db: Session, request: Request) -> tuple[int | None, str | None]:
    """Used only by the global safety-net handlers, where no route dependency has already
    resolved the current user/admin. Returns (tenant_id, actor_email), best-effort - a
    missing/invalid/expired cookie just yields (None, None), never raises."""
    from app.core.admin_security import parse_admin_session_token
    from app.core.config import settings
    from app.core.security import parse_session_token

    try:
        admin_token = request.cookies.get(settings.admin_session_cookie)
        admin_data = parse_admin_session_token(admin_token)
        if admin_data is not None:
            admin = db.get(PlatformAdmin, int(admin_data["admin_id"]))
            return None, (admin.email if admin is not None else None)

        user_token = request.cookies.get(settings.auth_session_cookie)
        user_data = parse_session_token(user_token)
        if user_data is not None:
            user = db.get(AppUser, int(user_data["user_id"]))
            return user_data.get("tenant_id"), (user.email if user is not None else None)
    except Exception:
        logger.exception("best_effort_actor_from_request failed")
    return None, None
