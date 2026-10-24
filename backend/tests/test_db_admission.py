"""Request-Annahme je Worker (app/core/db_admission.py): höchstens max_active Requests in der App,
Platz frei mit dem Antwortkopf, Ausnahmen für Healthcheck, Uploads und WebSockets; bei Überlast
Vorrang nach Abo-Stufe und Überlast-Seite nur für neue Nutzer."""

import asyncio
import json

from app.core import runtime_metrics
from app.core.db_admission import (
    PRIORITY_HIGH,
    PRIORITY_LOW,
    PRIORITY_NORMAL,
    ActiveUsers,
    DbAdmissionMiddleware,
    OverloadGuard,
    PriorityDirectory,
    PrioritySlots,
    RejectionLog,
)


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
        return middleware.slots().active

    assert asyncio.run(run()) == 0


# ── Priorität bei Überlast ────────────────────────────────────────────────────────────────


class _FakeRedis:
    def __init__(self, *, broken: bool = False) -> None:
        self.keys: dict[str, str] = {}
        self.broken = broken

    async def set(self, key, value, ex=None):
        if self.broken:
            raise ConnectionError("redis down")
        self.keys[key] = value

    async def exists(self, key):
        if self.broken:
            raise ConnectionError("redis down")
        return int(key in self.keys)


def _user_scope(user_id: int | None, path: str = "/api/protocols") -> dict:
    scope = _scope(path)
    scope["user_id"] = user_id
    return scope


def _guard(users: dict[int, tuple[int, int]], redis: _FakeRedis | None = None) -> OverloadGuard:
    directory = PriorityDirectory()
    directory._users = dict(users)
    redis = redis or _FakeRedis()
    return OverloadGuard(
        directory=directory,
        active_users=ActiveUsers(900, lambda: redis),
        rejections=RejectionLog(),
        thresholds={PRIORITY_LOW: 0.75, PRIORITY_NORMAL: 1.0},
        identify=lambda scope: scope.get("user_id"),
    )


def _body_collector(responses: list[tuple[int, dict]]):
    status: list[int] = []

    async def send(message):
        if message["type"] == "http.response.start":
            status.append(message["status"])
        elif message["type"] == "http.response.body" and status:
            body = message.get("body") or b""
            responses.append((status[-1], json.loads(body) if body.startswith(b"{") else {}))
    return send


def test_free_slots_go_to_the_highest_waiting_priority_first():
    async def run():
        slots = PrioritySlots(1)
        assert await slots.acquire(PRIORITY_LOW, 1)
        order: list[int] = []

        async def wait(priority: int):
            assert await slots.acquire(priority, 1)
            order.append(priority)
            slots.release()

        tasks = []
        for priority in (PRIORITY_LOW, PRIORITY_NORMAL, PRIORITY_HIGH, PRIORITY_NORMAL):
            tasks.append(asyncio.create_task(wait(priority)))
            await asyncio.sleep(0)
        await asyncio.sleep(0.01)
        slots.release()
        await asyncio.gather(*tasks)
        return order, slots.active

    order, active = asyncio.run(run())
    assert order == [PRIORITY_HIGH, PRIORITY_NORMAL, PRIORITY_NORMAL, PRIORITY_LOW]
    assert active == 0


def test_cancelled_or_timed_out_waiters_do_not_leak_slots():
    async def run():
        slots = PrioritySlots(1)
        assert await slots.acquire(PRIORITY_NORMAL, 1)
        assert await slots.acquire(PRIORITY_NORMAL, 0.01) is False
        cancelled = asyncio.create_task(slots.acquire(PRIORITY_HIGH, 5))
        await asyncio.sleep(0.01)
        cancelled.cancel()
        await asyncio.gather(cancelled, return_exceptions=True)
        slots.release()
        assert slots.active == 0 and slots.waiting == 0
        # Der Platz ist frei und sofort wieder vergeben.
        return await slots.acquire(PRIORITY_LOW, 0.01)

    assert asyncio.run(run()) is True


def test_pressure_rises_with_a_queue_and_decays_afterwards():
    async def run():
        slots = PrioritySlots(1, tau=0.05)
        assert await slots.acquire(PRIORITY_NORMAL, 1)
        waiter = asyncio.create_task(slots.acquire(PRIORITY_NORMAL, 5))
        await asyncio.sleep(0.3)
        busy = slots.pressure()
        slots.release()
        await waiter
        slots.release()
        await asyncio.sleep(0.3)
        return busy, slots.pressure()

    busy, idle = asyncio.run(run())
    assert busy > 1.5
    assert idle < 0.1


def test_new_low_priority_user_sees_overloaded_while_working_users_continue():
    async def run():
        runtime_metrics._take_counters()
        guard = _guard({1: (10, PRIORITY_LOW), 2: (10, PRIORITY_LOW), 3: (20, PRIORITY_HIGH), 4: (30, PRIORITY_NORMAL)})
        app = _App()
        app.release.set()
        middleware = DbAdmissionMiddleware(app, max_active=4, wait_seconds=1, guard=guard)
        responses: list[tuple[int, dict]] = []
        # Nutzer 2 arbeitet schon (vor der Überlast angenommen).
        await middleware(_user_scope(2), _receive, _body_collector(responses))
        middleware.slots().pressure = lambda: 0.9  # knapp: über "niedrig", unter "normal"
        for user_id in (1, 2, 3, 4, None):
            await middleware(_user_scope(user_id), _receive, _body_collector(responses))
        return responses, guard.rejections.take(), runtime_metrics._take_counters()

    responses, rejections, counters = asyncio.run(run())
    statuses = [status for status, _ in responses]
    assert statuses == [200, 503, 200, 200, 200, 200]
    assert responses[1][1]["code"] == "overloaded"
    assert rejections == [{"tenant_id": 10, "priority": PRIORITY_LOW, "rejected": 1, "users": 1, "pressure": 90}]
    assert counters["overload_rejected"] == 1


def test_high_priority_and_admin_api_are_never_rejected_up_front():
    async def run():
        guard = _guard({3: (20, PRIORITY_HIGH), 5: (30, PRIORITY_NORMAL)})
        guard.is_admin = lambda scope: True
        app = _App()
        app.release.set()
        middleware = DbAdmissionMiddleware(app, max_active=4, wait_seconds=1, guard=guard)
        middleware.slots().pressure = lambda: 50.0
        responses: list[tuple[int, dict]] = []
        await middleware(_user_scope(3), _receive, _body_collector(responses))
        await middleware(_user_scope(5, "/api/admin/system-status"), _receive, _body_collector(responses))
        await middleware(_user_scope(5), _receive, _body_collector(responses))
        return [status for status, _ in responses]

    assert asyncio.run(run()) == [200, 200, 503]


def test_admin_api_jumps_the_queue_only_with_a_valid_admin_session():
    async def run():
        guard = _guard({})
        guard.is_admin = lambda scope: scope.get("admin", False)
        order: list[str] = []
        gate = asyncio.Event()

        async def app(scope, receive, send):
            if scope.get("name") == "blocker":
                await gate.wait()
            order.append(scope.get("name"))
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        middleware = DbAdmissionMiddleware(app, max_active=1, wait_seconds=5, guard=guard)
        tasks = []
        for name, path, admin in (
            ("blocker", "/api/protocols", False),
            ("user", "/api/protocols", False),
            ("anonymous-admin-path", "/api/admin/system-status", False),
            ("admin", "/api/admin/system-status", True),
        ):
            scope = {**_scope(path), "name": name, "admin": admin}
            tasks.append(asyncio.create_task(middleware(scope, _receive, _collector([]))))
            await asyncio.sleep(0.01)
        gate.set()
        await asyncio.gather(*tasks)
        return order

    assert asyncio.run(run()) == ["blocker", "admin", "user", "anonymous-admin-path"]


def test_admitted_user_is_shared_as_active_via_redis():
    async def run():
        redis = _FakeRedis()
        first, second = _guard({1: (10, PRIORITY_LOW)}, redis), _guard({1: (10, PRIORITY_LOW)}, redis)
        app = _App()
        app.release.set()
        worker_a = DbAdmissionMiddleware(app, max_active=4, wait_seconds=1, guard=first)
        worker_b = DbAdmissionMiddleware(app, max_active=4, wait_seconds=1, guard=second)
        responses: list[tuple[int, dict]] = []
        await worker_a(_user_scope(1), _receive, _body_collector(responses))
        await asyncio.sleep(0)  # Markierung läuft als eigener Task
        worker_b.slots().pressure = lambda: 5.0
        await worker_b(_user_scope(1), _receive, _body_collector(responses))
        return [status for status, _ in responses], list(redis.keys)

    statuses, keys = asyncio.run(run())
    assert statuses == [200, 200]
    assert keys == ["hocx:overload:active:1"]


def test_redis_failure_admits_instead_of_locking_people_out():
    async def run():
        guard = _guard({1: (10, PRIORITY_LOW)}, _FakeRedis(broken=True))
        app = _App()
        app.release.set()
        middleware = DbAdmissionMiddleware(app, max_active=4, wait_seconds=1, guard=guard)
        middleware.slots().pressure = lambda: 5.0
        responses: list[tuple[int, dict]] = []
        await middleware(_user_scope(1), _receive, _body_collector(responses))
        return [status for status, _ in responses]

    assert asyncio.run(run()) == [200]


def test_unknown_user_gets_the_default_priority():
    directory = PriorityDirectory()
    directory._users = {1: (10, PRIORITY_HIGH)}
    assert directory.lookup(1) == (10, PRIORITY_HIGH)
    assert directory.lookup(2) == (None, PRIORITY_NORMAL)


def test_rejection_log_aggregates_and_logs_each_user_once_per_minute(caplog):
    log = RejectionLog()
    with caplog.at_level("WARNING", logger="app.core.db_admission"):
        for user_id in (1, 1, 1, 2):
            log.record(user_id=user_id, tenant_id=10, priority=PRIORITY_LOW, pressure=0.8)
        log.record(user_id=3, tenant_id=20, priority=PRIORITY_NORMAL, pressure=1.2)
    rows = sorted(log.take(), key=lambda row: row["tenant_id"])
    assert rows == [
        {"tenant_id": 10, "priority": PRIORITY_LOW, "rejected": 4, "users": 2, "pressure": 80},
        {"tenant_id": 20, "priority": PRIORITY_NORMAL, "rejected": 1, "users": 1, "pressure": 120},
    ]
    assert len([r for r in caplog.records if "Überlast" in r.getMessage()]) == 3
    assert log.take() == []


def test_upkeep_errors_reach_the_error_log(monkeypatch):
    from app.core import db_admission

    recorded: list[Exception] = []
    monkeypatch.setattr(db_admission, "_record_upkeep_error", lambda engine, exc: recorded.append(exc))
    guard = _guard({})

    def broken(engine):
        raise RuntimeError("permission denied for table plan")

    guard.directory.refresh = broken

    async def run():
        task = asyncio.create_task(db_admission.run_overload_upkeep(guard, object(), "backend:test:1", flush_seconds=0.01))
        await asyncio.sleep(0.05)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())
    assert recorded and isinstance(recorded[0], RuntimeError)
