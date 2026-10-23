"""Concurrency-Audit CONC-001: nichts Blockierendes im Event-Loop.

- Wartungs-Middleware lädt den Zustand im Threadpool, einmal für alle wartenden Requests, und
  wiederholt nach einem Fehler nicht bei jedem Request.
- Fehlerprotokoll der globalen Handler läuft im Threadpool und lässt bei Überlast Einträge aus,
  statt zu warten.
- Async-Funktionen mit DB-Zugriff laufen über core/offload.py (Regel im Checker).
"""

import asyncio
import threading
import time

from app.core import error_log, offload
from app.core.maintenance_middleware import MaintenanceMiddleware
from app.services import maintenance_service


async def _max_lag_while(coro, *, interval: float = 0.02) -> float:
    lag = 0.0
    stop = False

    async def ticker():
        nonlocal lag
        loop = asyncio.get_running_loop()
        while not stop:
            started = loop.time()
            await asyncio.sleep(interval)
            lag = max(lag, loop.time() - started - interval)

    task = asyncio.create_task(ticker())
    try:
        await coro
    finally:
        stop = True
        await task
    return lag


def _http_scope(path: str = "/api/protocols") -> dict:
    return {"type": "http", "path": path, "method": "GET", "headers": []}


def test_maintenance_middleware_loads_state_off_loop_and_single_flight(monkeypatch):
    calls = []

    def slow_load():
        calls.append(threading.get_ident())
        time.sleep(0.4)  # wie ein Pool-Checkout bei erschöpftem Pool
        return maintenance_service.EffectiveState()

    monkeypatch.setattr(maintenance_service, "load_effective_state", slow_load)
    maintenance_service.invalidate_cache()
    main_thread = threading.get_ident()
    passed = []

    async def downstream(scope, receive, send):
        passed.append(scope["path"])

    middleware = MaintenanceMiddleware(downstream)

    async def scenario():
        await asyncio.gather(*(middleware(_http_scope(), None, None) for _ in range(5)))

    lag = asyncio.run(_max_lag_while(scenario()))
    assert len(passed) == 5
    assert len(calls) == 1, "gleichzeitige Requests teilen sich eine Ladung"
    assert calls[0] != main_thread
    assert lag < 0.2, f"Event-Loop {lag:.2f}s blockiert"
    maintenance_service.invalidate_cache()


def test_failed_state_load_is_not_retried_on_every_request(monkeypatch):
    calls = []

    def failing_load():
        calls.append(1)
        raise RuntimeError("QueuePool limit reached")

    monkeypatch.setattr(maintenance_service, "load_effective_state", failing_load)
    maintenance_service.invalidate_cache()
    for _ in range(20):
        assert maintenance_service.current_effective_state().any_blocking is False
    assert len(calls) == 1
    maintenance_service.invalidate_cache()


class _Request:
    method = "GET"

    class url:
        path = "/api/x"

    cookies: dict = {}


def test_request_error_logging_runs_off_loop(monkeypatch):
    threads = []
    monkeypatch.setattr(error_log, "_record_request_error_sync", lambda request, exc, status: (threads.append(threading.get_ident()), time.sleep(0.3)))
    main_thread = threading.get_ident()
    lag = asyncio.run(_max_lag_while(error_log.record_request_error(_Request(), RuntimeError("x"), 500)))
    assert threads and threads[0] != main_thread
    assert lag < 0.2


def test_request_error_logging_drops_entries_when_overloaded(monkeypatch):
    started = threading.Event()
    release = threading.Event()

    def blocking(request, exc, status):
        started.set()
        release.wait(5)

    monkeypatch.setattr(error_log, "_record_request_error_sync", blocking)

    async def scenario():
        pending = [asyncio.create_task(error_log.record_request_error(_Request(), RuntimeError("x"), 500)) for _ in range(4)]
        await asyncio.sleep(0.2)
        began = time.monotonic()
        await error_log.record_request_error(_Request(), RuntimeError("fünfter"), 500)  # Slots belegt: sofort zurück
        dropped_fast = time.monotonic() - began < 0.1
        release.set()
        await asyncio.gather(*pending)
        return dropped_fast

    assert asyncio.run(scenario()) is True


def test_run_coroutine_in_thread_uses_its_own_loop():
    main_loop_ids = []

    async def work(value):
        await asyncio.sleep(0)
        return id(asyncio.get_running_loop()), threading.get_ident(), value

    async def scenario():
        main_loop_ids.append(id(asyncio.get_running_loop()))
        return await offload.run_coroutine_in_thread(work, 42)

    loop_id, thread_id, value = asyncio.run(scenario())
    assert value == 42
    assert loop_id != main_loop_ids[0]
    assert thread_id != threading.get_ident()
