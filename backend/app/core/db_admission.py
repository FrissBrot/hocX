"""Gleichzeitige HTTP-Requests je uvicorn-Worker an die Grösse des DB-Pools binden (Lasttest
2026-10-22, Nachtrag zum Concurrency-Audit CONC-010).

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

Ausgenommen: WebSockets, /api/health (Healthcheck soll auch unter Last antworten) und Pfade
mit eigener Annahme bzw. langem Upload-Body (``skip_prefixes``) - ein Request, der 150 MB
empfängt, würde sonst einen Platz ohne DB-Arbeit blockieren.
"""

from __future__ import annotations

import asyncio
import time

from starlette.responses import JSONResponse

from app.core import runtime_metrics


class DbAdmissionMiddleware:
    def __init__(self, app, *, max_active: int, wait_seconds: float, skip_prefixes: tuple[str, ...] = (), skip_paths: tuple[str, ...] = ()):
        self.app = app
        self.max_active = max_active
        self.wait_seconds = wait_seconds
        self.skip_prefixes = skip_prefixes
        self.skip_paths = set(skip_paths)
        self._slots: dict[int, asyncio.Semaphore] = {}

    def _semaphore(self) -> asyncio.Semaphore:
        loop_id = id(asyncio.get_running_loop())
        if loop_id not in self._slots:
            self._slots[loop_id] = asyncio.Semaphore(self.max_active)
        return self._slots[loop_id]

    def _applies(self, scope) -> bool:
        if scope["type"] != "http" or scope.get("method") == "OPTIONS":
            return False
        path = scope["path"]
        return path not in self.skip_paths and not path.startswith(self.skip_prefixes)

    async def __call__(self, scope, receive, send):
        if not self._applies(scope):
            return await self.app(scope, receive, send)
        semaphore = self._semaphore()
        started = time.monotonic()
        try:
            await asyncio.wait_for(semaphore.acquire(), timeout=self.wait_seconds)
        except asyncio.TimeoutError:
            runtime_metrics.count("admission_timeouts")
            return await JSONResponse(
                {"detail": "Der Server ist gerade ausgelastet. Bitte gleich erneut versuchen.", "code": "db_busy"},
                503,
                headers={"Retry-After": "5", "Cache-Control": "no-store"},
            )(scope, receive, send)
        runtime_metrics.observe_max("admission_wait_max_ms", (time.monotonic() - started) * 1000)
        released = False

        def release() -> None:
            nonlocal released
            if not released:
                released = True
                semaphore.release()

        async def releasing_send(message):
            if message["type"] == "http.response.start":
                release()
            await send(message)

        try:
            await self.app(scope, receive, releasing_send)
        finally:
            release()
