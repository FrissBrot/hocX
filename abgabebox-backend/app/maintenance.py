"""Wartungssperre der öffentlichen Abgabebox (Gegenstück zu backend/app/core/maintenance_middleware.py).

Liest den Zustand über die SECURITY-DEFINER-Funktion maintenance_effective_state() (Migration
0114) - die eingeschränkte Rolle hocx_abgabebox braucht dafür keinen Tabellenzugriff. Während
voller Wartung ist die ganze öffentliche API gesperrt, bei gesperrten Schreib-/Upload-Vorgängen
nur POST. Ist die Datenbank nicht erreichbar, gilt der zuletzt bekannte Zustand weiter.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import text
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import settings
from app.db import engine

_logger = logging.getLogger(__name__)
EXEMPT_PATHS = ("/api/health", "/api/public/maintenance-status")


@dataclass(frozen=True)
class State:
    full_active: bool = False
    writes_blocked: bool = False
    uploads_blocked: bool = False
    estimated_end_at: datetime | None = None
    loaded_at: float = 0.0


_lock = threading.Lock()
_cached: State | None = None
# Nach einem Ladefehler den letzten Stand weiterverwenden, statt bei jedem Request erneut auf
# die Datenbank zu warten (Concurrency-Audit CONC-001).
_FAILURE_BACKOFF_SECONDS = 5.0
_last_failure_at: float | None = None
_inflight: dict[int, "asyncio.Task[State]"] = {}


def _usable_cached() -> State | None:
    with _lock:
        cached, failed_at = _cached, _last_failure_at
    now = time.monotonic()
    if cached is not None and now - cached.loaded_at < settings.maintenance_cache_seconds:
        return cached
    if failed_at is not None and now - failed_at < _FAILURE_BACKOFF_SECONDS:
        return cached or State()
    return None


def current_state() -> State:
    """Synchron und potenziell blockierend - in der Middleware state_async() verwenden."""
    global _cached, _last_failure_at
    if (usable := _usable_cached()) is not None:
        return usable
    try:
        with engine.connect() as conn:
            row = conn.execute(text("SELECT * FROM maintenance_effective_state()")).one()._mapping
        state = State(bool(row["full_active"]), bool(row["writes_blocked"]), bool(row["uploads_blocked"]), row["estimated_end_at"], time.monotonic())
    except Exception:
        _logger.warning("Wartungszustand nicht ladbar - letzter Stand gilt", exc_info=True)
        with _lock:
            _last_failure_at = time.monotonic()
            return _cached or State()
    with _lock:
        _cached, _last_failure_at = state, None
    return state


async def state_async() -> State:
    """Blockiert den Event-Loop nie: Nachladen einmal je Loop im Threadpool."""
    if (usable := _usable_cached()) is not None:
        return usable
    loop = asyncio.get_running_loop()
    task = _inflight.get(id(loop))
    if task is None or task.done():
        task = loop.create_task(asyncio.to_thread(current_state))
        _inflight[id(loop)] = task
    return await asyncio.shield(task)


def retry_after(state: State) -> int:
    if state.estimated_end_at is None:
        return 120
    return max(30, min(int((state.estimated_end_at - datetime.now(timezone.utc)).total_seconds()), 900))


class MaintenanceMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if scope["type"] != "http" or not path.startswith("/api") or path in EXEMPT_PATHS or scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return
        state = await state_async()
        method = scope.get("method", "GET")
        blocked = state.full_active or (method not in ("GET", "HEAD") and (state.writes_blocked or state.uploads_blocked))
        if not blocked:
            await self.app(scope, receive, send)
            return
        body = json.dumps({"detail": "Die Abgabebox wird gerade gewartet. Bitte später erneut versuchen.", "code": "maintenance"}).encode()
        await send({"type": "http.response.start", "status": 503, "headers": [
            (b"content-type", b"application/json"), (b"retry-after", str(retry_after(state)).encode()),
            (b"cache-control", b"no-store"), (b"content-length", str(len(body)).encode()),
        ]})
        await send({"type": "http.response.body", "body": body})
