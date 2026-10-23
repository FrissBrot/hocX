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
import re
import traceback as traceback_module

from fastapi import Request
from sqlalchemy.orm import Session

from app.models import AppUser, PlatformAdmin, SystemErrorLog

logger = logging.getLogger(__name__)

_MAX_MESSAGE_LENGTH = 4000
_MAX_TRACEBACK_LENGTH = 20000

# Personendaten aus Fehlertexten entfernen (Datenschutz-Audit PRIV-002). Die Engines laufen mit
# hide_parameters=True; das hier fängt ab, was trotzdem im Text steht: Postgres-Details bei
# Constraint-Verletzungen, E-Mail-Adressen in eigenen Meldungen, Parameterblöcke fremder Engines.
_REDACTIONS = (
    # DETAIL:  Key (email)=(max@example.ch) already exists.  /  Failing row contains (...)
    (re.compile(r"(Key \([^)]*\)=\().*?(\) (?:already exists|is not present|is still referenced|conflicts))"), r"\1<redacted>\2"),
    (re.compile(r"(Failing row contains \().*(\)\.?)$", re.M), r"\1<redacted>\2"),
    (re.compile(r"\[parameters: .*?\](?=\n|$)", re.S | re.M), "[parameters: <redacted>]"),
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "<email>"),
)


def redact(text: str) -> str:
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


def record_system_error(
    db: Session,
    *,
    exc: Exception,
    request: Request | None = None,
    tenant_id: int | None = None,
    actor_user_id: int | None = None,
    actor_admin_id: int | None = None,
    status_code: int | None = None,
    source: str = "backend",
) -> None:
    """Akteure nur als ID (PRIV-002): die Admin-Ansicht löst die E-Mail beim Lesen auf, nach dem
    Löschen des Kontos bleibt nichts zurück."""
    try:
        entry = SystemErrorLog(
            source=source,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            actor_admin_id=actor_admin_id,
            request_method=request.method if request is not None else None,
            request_path=request.url.path if request is not None else None,
            status_code=status_code,
            error_type=type(exc).__name__,
            error_message=redact(str(exc))[:_MAX_MESSAGE_LENGTH],
            traceback=redact("".join(traceback_module.format_exception(type(exc), exc, exc.__traceback__)))[:_MAX_TRACEBACK_LENGTH],
        )
        db.add(entry)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to persist system_error_log entry (original error: %s: %s)", type(exc).__name__, redact(str(exc)))


def best_effort_actor_from_request(db: Session, request: Request) -> tuple[int | None, int | None, int | None]:
    """Used only by the global safety-net handlers, where no route dependency has already
    resolved the current user/admin. Returns (tenant_id, actor_user_id, actor_admin_id),
    best-effort - a missing/invalid/expired cookie just yields Nones, never raises. Der Mandant
    kommt aus dem Konto: Sessions tragen seit der Einzelmandanten-Umstellung kein tenant_id mehr."""
    from app.core.admin_security import parse_admin_session_token
    from app.core.config import settings
    from app.core.security import parse_session_token

    try:
        admin_token = request.cookies.get(settings.admin_session_cookie)
        admin_data = parse_admin_session_token(admin_token)
        if admin_data is not None:
            admin = db.get(PlatformAdmin, int(admin_data["admin_id"]))
            return None, None, (admin.id if admin is not None else None)

        user_token = request.cookies.get(settings.auth_session_cookie)
        user_data = parse_session_token(user_token)
        if user_data is not None:
            user = db.get(AppUser, int(user_data["user_id"]))
            if user is not None:
                return user.tenant_id, user.id, None
    except Exception:
        logger.exception("best_effort_actor_from_request failed")
    return None, None, None


# --- Globale Handler (main.py): nie im Event-Loop, nie aus dem Request-Pool -----------------
# Concurrency-Audit CONC-001: die Handler öffneten SessionLocal() synchron im Event-Loop. Bei
# erschöpftem Pool (genau dann häufen sich 500er) stand dadurch der ganze Worker bis zum
# Pool-Timeout. Jetzt: eigene ungepoolte Verbindung mit kurzem Connect-Timeout im Threadpool,
# höchstens _ERROR_LOG_SLOTS Einträge gleichzeitig - bei einer Fehlerlawine wird der Rest nur ins
# Log geschrieben statt die Datenbank zusätzlich zu belasten.
import threading  # noqa: E402

_ERROR_LOG_SLOTS = threading.BoundedSemaphore(4)
_error_engine = None
_error_engine_lock = threading.Lock()


def _error_log_session() -> Session:
    global _error_engine
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    from app.core.config import settings

    with _error_engine_lock:
        if _error_engine is None:
            _error_engine = create_engine(
                settings.app_database_url or settings.database_url,
                poolclass=NullPool,
                hide_parameters=True,
                connect_args={"connect_timeout": 3, "application_name": f"hocx-{settings.process_kind}-errorlog"},
            )
    return Session(bind=_error_engine, autoflush=False, future=True)


def _record_request_error_sync(request: Request, exc: Exception, status_code: int) -> None:
    try:
        db = _error_log_session()
    except Exception:
        logger.exception("Fehlerprotokoll-Verbindung nicht verfügbar (original error: %s: %s)", type(exc).__name__, redact(str(exc)))
        return
    try:
        tenant_id, actor_user_id, actor_admin_id = best_effort_actor_from_request(db, request)
        record_system_error(db, exc=exc, request=request, tenant_id=tenant_id, actor_user_id=actor_user_id, actor_admin_id=actor_admin_id, status_code=status_code)
    finally:
        db.close()


async def record_request_error(request: Request, exc: Exception, status_code: int) -> None:
    """Für die globalen async Exception-Handler. Wirft nie."""
    from starlette.concurrency import run_in_threadpool

    if not _ERROR_LOG_SLOTS.acquire(blocking=False):
        logger.error("Fehlerprotokoll überlastet, Eintrag nur im Log: %s %s -> %s: %s", request.method, request.url.path, type(exc).__name__, redact(str(exc)))
        return
    try:
        await run_in_threadpool(_record_request_error_sync, request, exc, status_code)
    except Exception:
        logger.exception("Fehlerprotokoll fehlgeschlagen")
    finally:
        _ERROR_LOG_SLOTS.release()
