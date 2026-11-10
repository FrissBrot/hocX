"""Gleichzeitige HTTP-Requests je uvicorn-Worker an die Grösse des DB-Pools binden (Lasttest
2026-10-22, Nachtrag zum Concurrency-Audit CONC-010) und bei Überlast nach Abo priorisieren.

FastAPI führt jede synchrone Stufe eines Requests einzeln im anyio-Threadpool aus (40 Threads):
sync-Dependencies wie get_current_user, die Route selbst und die Validierung des
response_model. Zwischen den Stufen gibt der Request seinen Thread ab, behält aber die
DB-Verbindung ("idle in transaction"). Unter Last (u250) kippte das in einen Stau: Threads
warteten im Pool (12 + 8) auf Verbindungen, die Requests hielten, die selbst auf einen Thread
warteten - bis pool_timeout, dann 503 db_busy für alle. p95 stieg von 0,2 s auf 15 s.

Diese Middleware lässt höchstens ``max_active`` Requests gleichzeitig in die App (Pool minus
Reserve für WebSockets, Hintergrund-Loops und das Fehlerprotokoll). Die übrigen warten im
Event-Loop - ohne Thread, ohne Verbindung - bis ``wait_seconds``, dann 503 db_busy. Der Platz
wird mit dem Antwortkopf frei: Streaming-Antworten (release_for_stream) belegen ihn nicht für
die Dauer des Downloads.

Priorität bei Überlast (Nutzerentscheid 2026-10-23, Migration 0151): Jeder Plan hat eine Stufe
(niedrig/normal/hoch), die der Plattform-Admin im Preiskatalog setzt.
- Wartende bekommen freie Plätze nach Stufe (FIFO je Stufe), Plattform-Admin-API immer zuerst.
- Steigt die geglättete Auslastung über die Schwelle einer Stufe, bekommen *neue* Nutzer dieser
  Stufe sofort 503 ``overloaded`` und das Frontend zeigt die Überlast-Seite. Wer in den letzten
  ``active_window`` Sekunden angenommen wurde (Redis, über alle Worker), arbeitet weiter - so
  verliert niemand mitten in einem Protokoll seine Sitzung.
- Anonyme Requests (Anmeldung, öffentliche Links) werden nie vorab abgewiesen: der Mandant ist
  dort unbekannt, und die Anmeldung soll die Meldung erst nach dem Login zeigen.
Jede Abweisung landet im Container-Log, in den Laufzeitkennzahlen und - je Prozess alle ~15 s
zusammengefasst - in ``overload_rejection`` (Monitoring /admin/system).

Ausgenommen: WebSockets, /api/health (Healthcheck soll auch unter Last antworten) und Pfade
mit eigener Annahme bzw. langem Upload-Body (``skip_prefixes``) - ein Request, der 150 MB
empfängt, würde sonst einen Platz ohne DB-Arbeit blockieren.
"""

from __future__ import annotations

import asyncio
import heapq
import itertools
import logging
import math
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from starlette.responses import JSONResponse

from app.core import runtime_metrics

_logger = logging.getLogger(__name__)

PRIORITY_LOW, PRIORITY_NORMAL, PRIORITY_HIGH = 0, 1, 2
# Plattform-Admin-API: Notfallfunktionen und Monitoring müssen auch unter Last durchkommen.
PRIORITY_ADMIN = 3
PRESSURE_TAU_SECONDS = 10.0
ACTIVE_MARK_SECONDS = 60.0
REJECTION_LOG_SECONDS = 60.0
ACTIVE_KEY = "hocx:overload:active:{user_id}"


class PrioritySlots:
    """Semaphore mit Vorrang: ein frei werdender Platz geht direkt an den Wartenden mit der
    höchsten Stufe (bei gleicher Stufe an den ältesten). Dazu die geglättete Auslastung
    (in Arbeit + wartend je Platz, exponentiell über ``tau`` Sekunden) als Überlast-Signal.
    Nur innerhalb eines Event-Loops verwenden."""

    def __init__(self, capacity: int, *, tau: float = PRESSURE_TAU_SECONDS) -> None:
        self.capacity = capacity
        self.active = 0
        self.waiting = 0
        self._tau = tau
        self._heap: list[tuple[int, int, asyncio.Future]] = []
        self._seq = itertools.count()
        self._ema = 0.0
        self._level = 0.0
        self._at = time.monotonic()

    def _observe(self) -> None:
        # Stückweise konstant: der bisherige Momentanwert galt seit _at.
        now = time.monotonic()
        weight = math.exp(-(now - self._at) / self._tau)
        self._ema = self._ema * weight + self._level * (1 - weight)
        self._level = (self.active + self.waiting) / self.capacity
        self._at = now

    def pressure(self) -> float:
        self._observe()
        return self._ema

    async def acquire(self, priority: int, timeout: float) -> bool:
        # Wartende gibt es nur, solange alle Plätze belegt sind (release übergibt direkt).
        if self.active < self.capacity:
            self.active += 1
            self._observe()
            return True
        future = asyncio.get_running_loop().create_future()
        heapq.heappush(self._heap, (-priority, next(self._seq), future))
        self.waiting += 1
        self._observe()
        try:
            await asyncio.wait_for(future, timeout)
            return True
        except asyncio.TimeoutError:
            # Platz im selben Moment übergeben, in dem die Frist ablief: er gehört diesem Request.
            return future.done() and not future.cancelled()
        except BaseException:
            # Abbruch genau in dem Moment, in dem der Platz übergeben wurde: weiterreichen.
            if future.done() and not future.cancelled():
                self.release()
            raise
        finally:
            self.waiting -= 1
            self._observe()

    def release(self) -> None:
        while self._heap:
            _, _, future = heapq.heappop(self._heap)
            if not future.done():
                future.set_result(None)
                return
        self.active -= 1
        self._observe()


@dataclass
class PriorityDirectory:
    """Nutzer -> (Mandant, Stufe) für die Middleware, ohne DB im Request-Pfad: alle ~60 s aus der
    Datenbank geladen (run_overload_upkeep). Unbekannte Nutzer (neu angelegt) gelten bis zum
    nächsten Laden als ``default``."""

    default: int = PRIORITY_NORMAL
    _users: dict[int, tuple[int, int]] = field(default_factory=dict)

    def lookup(self, user_id: int) -> tuple[int | None, int]:
        entry = self._users.get(user_id)
        return (entry[0], entry[1]) if entry else (None, self.default)

    def refresh(self, engine: Engine) -> None:
        with engine.connect() as conn:
            self.load(conn)

    def load(self, conn: Connection) -> None:
        rows = conn.execute(
            text(
                "SELECT u.id, u.tenant_id, COALESCE(p.load_priority, :default) "
                "FROM app_user u JOIN tenant t ON t.id = u.tenant_id LEFT JOIN plan p ON p.code = t.plan_code"
            ),
            {"default": self.default},
        ).all()
        self._users = {int(user_id): (int(tenant_id), int(priority)) for user_id, tenant_id, priority in rows}


class ActiveUsers:
    """Wer in den letzten ``window_seconds`` angenommen wurde, gilt als arbeitend und wird nie vorab
    abgewiesen. Über Redis geteilt, weil die Requests eines Nutzers auf beide Worker verteilt
    werden; je Worker höchstens einmal pro Minute und Nutzer geschrieben. Ist Redis gestört,
    gilt jeder als arbeitend (lieber Last als fälschlich Ausgesperrte)."""

    def __init__(self, window_seconds: float, redis_factory: Callable[[], object]) -> None:
        self.window = window_seconds
        self._redis_factory = redis_factory
        self._seen: dict[int, float] = {}
        self._marked: dict[int, float] = {}
        self._tasks: set[asyncio.Task] = set()

    def touch(self, user_id: int) -> None:
        now = time.monotonic()
        self._seen[user_id] = now
        if now - self._marked.get(user_id, -math.inf) < ACTIVE_MARK_SECONDS:
            return
        self._marked[user_id] = now
        task = asyncio.get_running_loop().create_task(self._mark(user_id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _mark(self, user_id: int) -> None:
        try:
            await self._redis_factory().set(ACTIVE_KEY.format(user_id=user_id), "1", ex=int(self.window))
        except Exception:
            # Best effort: fehlt die Markierung, sieht dieser Nutzer bei Überlast im schlimmsten
            # Fall die Überlast-Seite - der Fehler selbst ist im Redis-Healthcheck sichtbar.
            self._marked.pop(user_id, None)
            _logger.warning("Aktivität für Überlast-Schutz nicht gespeichert", exc_info=True)

    async def is_active(self, user_id: int) -> bool:
        if time.monotonic() - self._seen.get(user_id, -math.inf) < self.window:
            return True
        try:
            return bool(await self._redis_factory().exists(ACTIVE_KEY.format(user_id=user_id)))
        except Exception:
            _logger.warning("Aktivität für Überlast-Schutz nicht lesbar - Nutzer wird angenommen", exc_info=True)
            return True

    def prune(self) -> None:
        cutoff = time.monotonic() - self.window
        self._seen = {user_id: at for user_id, at in self._seen.items() if at >= cutoff}
        self._marked = {user_id: at for user_id, at in self._marked.items() if at >= cutoff}


class RejectionLog:
    """Abweisungen je (Mandant, Stufe) bis zum nächsten Schreiben; dazu höchstens eine Logzeile
    je Nutzer und Minute (Retry-After lässt das Frontend regelmässig neu anfragen)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: dict[tuple[int | None, int], tuple[int, set[int], float]] = {}
        self._logged: dict[int, float] = {}

    def record(self, *, user_id: int, tenant_id: int | None, priority: int, pressure: float) -> None:
        runtime_metrics.count("overload_rejected")
        with self._lock:
            rejected, users, peak = self._pending.get((tenant_id, priority), (0, set(), 0.0))
            users.add(user_id)
            self._pending[(tenant_id, priority)] = (rejected + 1, users, max(peak, pressure))
            now = time.monotonic()
            if now - self._logged.get(user_id, -math.inf) < REJECTION_LOG_SECONDS:
                return
            self._logged[user_id] = now
        _logger.warning(
            "Überlast: neuer Nutzer abgewiesen (user_id=%s tenant_id=%s priority=%s auslastung=%.0f%%)",
            user_id, tenant_id, priority, pressure * 100,
        )

    def take(self) -> list[dict]:
        with self._lock:
            pending, self._pending = self._pending, {}
            cutoff = time.monotonic() - REJECTION_LOG_SECONDS
            self._logged = {user_id: at for user_id, at in self._logged.items() if at >= cutoff}
        return [
            {"tenant_id": tenant_id, "priority": priority, "rejected": rejected, "users": len(users), "pressure": round(peak * 100)}
            for (tenant_id, priority), (rejected, users, peak) in pending.items()
        ]

    def flush(self, engine: Engine, instance: str) -> None:
        rows = self.take()
        if rows:
            with engine.begin() as conn:
                self.write(conn, instance, rows)

    @staticmethod
    def write(conn: Connection, instance: str, rows: list[dict]) -> None:
        for row in rows:
            # Mandant inzwischen gelöscht: die FK würde den ganzen Block verwerfen.
            conn.execute(
                text(
                    "INSERT INTO overload_rejection (instance, tenant_id, load_priority, rejected, users, pressure_percent) "
                    "SELECT :instance, t.id, :priority, :rejected, :users, :pressure "
                    "FROM (SELECT CAST(:tenant_id AS bigint) AS id) AS t "
                    "WHERE t.id IS NULL OR EXISTS (SELECT 1 FROM tenant WHERE tenant.id = t.id)"
                ),
                {"instance": instance, **row},
            )


@dataclass
class OverloadGuard:
    """Was die Middleware für die Priorisierung braucht. ``thresholds`` je Stufe: ab dieser
    Auslastung werden neue Nutzer abgewiesen; fehlt eine Stufe, wird sie nie vorab abgewiesen."""

    directory: PriorityDirectory
    active_users: ActiveUsers
    rejections: RejectionLog
    thresholds: dict[int, float]
    identify: Callable[[dict], int | None]
    # Gültige Plattform-Admin-Session (signiertes Cookie): nur dann Vorrang auf /api/admin/ -
    # sonst könnte eine anonyme Flut auf die Admin-API Mandanten-Requests verdrängen.
    is_admin: Callable[[dict], bool] = lambda scope: False


async def run_overload_upkeep(guard: OverloadGuard, engine: Engine, instance: str, *, flush_seconds: float = 15.0, refresh_seconds: float = 60.0) -> None:
    """Lifespan-Task je Worker: Abweisungen schreiben, Stufen neu laden, Aktivitäts-Cache kürzen.
    Über eine eigene, ungepoolte Verbindung (wie runtime_metrics) - gerade bei Überlast."""
    last_refresh = -math.inf
    while True:
        try:
            if time.monotonic() - last_refresh >= refresh_seconds:
                await asyncio.to_thread(guard.directory.refresh, engine)
                guard.active_users.prune()
                last_refresh = time.monotonic()
            await asyncio.to_thread(guard.rejections.flush, engine, instance)
        except Exception as exc:
            # Läuft ausserhalb eines Requests: ohne eigenes Logging verschwände der Fehler, und alle
            # Nutzer liefen still auf der Standardstufe. Über die ungepoolte Engine, nicht den Pool.
            _logger.exception("Überlast-Schutz: Stufen laden oder Abweisungen schreiben fehlgeschlagen")
            await asyncio.to_thread(_record_upkeep_error, engine, exc)
        await asyncio.sleep(flush_seconds)


def _record_upkeep_error(engine: Engine, exc: Exception) -> None:
    from sqlalchemy.orm import Session

    from app.core.error_log import record_system_error

    try:
        with Session(bind=engine) as db:
            record_system_error(db, exc=exc)
    except Exception:
        _logger.exception("Fehler des Überlast-Schutzes nicht ins Fehlerprotokoll geschrieben")


class DbAdmissionMiddleware:
    def __init__(
        self,
        app,
        *,
        max_active: int,
        wait_seconds: float,
        skip_prefixes: tuple[str, ...] = (),
        skip_paths: tuple[str, ...] = (),
        admin_prefix: str = "/api/admin/",
        guard: OverloadGuard | None = None,
    ):
        self.app = app
        self.max_active = max_active
        self.wait_seconds = wait_seconds
        self.skip_prefixes = skip_prefixes
        self.skip_paths = set(skip_paths)
        self.admin_prefix = admin_prefix
        self.guard = guard
        self._slots: dict[int, PrioritySlots] = {}

    def slots(self) -> PrioritySlots:
        loop_id = id(asyncio.get_running_loop())
        if loop_id not in self._slots:
            self._slots[loop_id] = PrioritySlots(self.max_active)
        return self._slots[loop_id]

    def _applies(self, scope) -> bool:
        if scope["type"] != "http" or scope.get("method") == "OPTIONS":
            return False
        path = scope["path"]
        return path not in self.skip_paths and not path.startswith(self.skip_prefixes)

    async def _excluded(self, guard: OverloadGuard, slots: PrioritySlots, user_id: int, tenant_id: int | None, priority: int) -> bool:
        threshold = guard.thresholds.get(priority)
        if threshold is None:
            return False
        pressure = slots.pressure()
        if pressure < threshold or await guard.active_users.is_active(user_id):
            return False
        guard.rejections.record(user_id=user_id, tenant_id=tenant_id, priority=priority, pressure=pressure)
        return True

    async def __call__(self, scope, receive, send):
        if not self._applies(scope):
            return await self.app(scope, receive, send)
        slots = self.slots()
        guard = self.guard
        user_id = tenant_id = None
        priority = PRIORITY_NORMAL
        if guard is not None and scope["path"].startswith(self.admin_prefix):
            if guard.is_admin(scope):
                priority = PRIORITY_ADMIN
        elif guard is not None:
            user_id = guard.identify(scope)
            if user_id is not None:
                tenant_id, priority = guard.directory.lookup(user_id)
                if await self._excluded(guard, slots, user_id, tenant_id, priority):
                    return await _overloaded(scope, receive, send)
        started = time.monotonic()
        if not await slots.acquire(priority, self.wait_seconds):
            runtime_metrics.count("admission_timeouts")
            return await JSONResponse(
                {"detail": "Der Server ist gerade ausgelastet. Bitte gleich erneut versuchen.", "code": "db_busy"},
                503,
                headers={"Retry-After": "5", "Cache-Control": "no-store"},
            )(scope, receive, send)
        runtime_metrics.observe_max("admission_wait_max_ms", (time.monotonic() - started) * 1000)
        if user_id is not None:
            guard.active_users.touch(user_id)
        released = False

        def release() -> None:
            nonlocal released
            if not released:
                released = True
                slots.release()

        async def releasing_send(message):
            if message["type"] == "http.response.start":
                release()
            await send(message)

        try:
            await self.app(scope, receive, releasing_send)
        finally:
            release()


def _overloaded(scope, receive, send) -> Awaitable[None]:
    return JSONResponse(
        {"detail": "Die Server sind gerade überlastet. Bitte versuchen Sie es in einigen Minuten erneut.", "code": "overloaded"},
        503,
        headers={"Retry-After": "60", "Cache-Control": "no-store"},
    )(scope, receive, send)
