"""Request-Annahme je Worker (app/core/db_admission.py): höchstens max_active Requests in der App,
Platz frei mit dem Antwortkopf, Ausnahmen für Healthcheck, Uploads und WebSockets."""

import asyncio

from app.core import runtime_metrics
from app.core.db_admission import DbAdmissionMiddleware


def _scope(path: str = "/api/protocols", method: str = "GET", kind: str = "http") -> dict:
    return {"type": kind, "method": method, "path": path, "headers": []}


async def _receive():
    return {"type": "http.request", "body": b"", "more_body": False}


class _App:
    """Hält jeden Request bis release gesetzt ist; streamt optional nach dem Antwortkopf weiter."""

    def __init__(self, *, stream_after_start: bool = False) -> None:
        self.active = 0
        self.peak = 0
        self.release = asyncio.Event()
        self.started_body = asyncio.Event()
        self.stream_after_start = stream_after_start

    async def __call__(self, scope, receive, send):
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            if self.stream_after_start:
                await send({"type": "http.response.start", "status": 200, "headers": []})
                self.started_body.set()
                await self.release.wait()
            else:
                await self.release.wait()
                await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})
        finally:
            self.active -= 1


def _collector(statuses: list[int]):
    async def send(message):
        if message["type"] == "http.response.start":
            statuses.append(message["status"])
    return send


def test_limits_concurrent_requests_and_queues_the_rest():
    async def run():
        app = _App()
        middleware = DbAdmissionMiddleware(app, max_active=2, wait_seconds=5)
        statuses: list[int] = []
        tasks = [asyncio.create_task(middleware(_scope(), _receive, _collector(statuses))) for _ in range(5)]
        await asyncio.sleep(0.05)
        assert app.active == 2
        app.release.set()
        await asyncio.gather(*tasks)
        return app.peak, statuses

    peak, statuses = asyncio.run(run())
    assert peak == 2
    assert statuses == [200] * 5


def test_waiting_too_long_returns_503_db_busy_and_counts():
    async def run():
        runtime_metrics._take_counters()
        app = _App()
        middleware = DbAdmissionMiddleware(app, max_active=1, wait_seconds=0.1)
        statuses: list[int] = []
        first = asyncio.create_task(middleware(_scope(), _receive, _collector(statuses)))
        await asyncio.sleep(0.01)
        await middleware(_scope(), _receive, _collector(statuses))
        app.release.set()
        await first
        return statuses, runtime_metrics._take_counters()

    statuses, counters = asyncio.run(run())
    assert statuses == [503, 200]
    assert counters["admission_timeouts"] == 1


def test_slot_is_released_with_response_start_for_streaming_responses():
    async def run():
        streaming = _App(stream_after_start=True)
        middleware = DbAdmissionMiddleware(streaming, max_active=1, wait_seconds=0.5)
        statuses: list[int] = []
        download = asyncio.create_task(middleware(_scope("/api/files/x/download"), _receive, _collector(statuses)))
        await streaming.started_body.wait()
        # Der Download streamt noch, der nächste Request kommt trotzdem sofort hinein.
        second = asyncio.create_task(middleware(_scope(), _receive, _collector(statuses)))
        await asyncio.sleep(0.05)
        active_during_stream = streaming.active
        streaming.release.set()
        await asyncio.gather(download, second)
        return active_during_stream, statuses

    active, statuses = asyncio.run(run())
    assert active == 2
    assert statuses == [200, 200]


def test_health_uploads_preflight_and_websockets_bypass_the_limit():
    async def run():
        app = _App()
        middleware = DbAdmissionMiddleware(
            app, max_active=1, wait_seconds=0.1, skip_paths=("/api/health",), skip_prefixes=("/api/files/gallery-uploads",)
        )
        statuses: list[int] = []
        blocker = asyncio.create_task(middleware(_scope(), _receive, _collector(statuses)))
        await asyncio.sleep(0.01)
        bypass = [
            asyncio.create_task(middleware(scope, _receive, _collector(statuses)))
            for scope in (
                _scope("/api/health"),
                _scope("/api/files/gallery-uploads", "POST"),
                _scope(method="OPTIONS"),
                _scope("/api/ws/protocols/1", kind="websocket"),
            )
        ]
        await asyncio.sleep(0.05)
        active = app.active
        app.release.set()
        await asyncio.gather(blocker, *bypass)
        return active, statuses

    active, statuses = asyncio.run(run())
    assert active == 5
    assert 503 not in statuses


def test_slot_is_released_when_the_app_raises():
    async def run():
        async def failing(scope, receive, send):
            raise RuntimeError("boom")

        middleware = DbAdmissionMiddleware(failing, max_active=1, wait_seconds=0.1)
        for _ in range(2):
            try:
                await middleware(_scope(), _receive, _collector([]))
            except RuntimeError:
                pass
        return middleware._semaphore().locked()

    assert asyncio.run(run()) is False
