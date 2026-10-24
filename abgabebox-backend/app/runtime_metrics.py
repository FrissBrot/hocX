# GENERIERT aus backend/app/core/runtime_metrics.py - nicht von Hand bearbeiten, siehe scripts/sync-objstore-client.sh
"""Laufzeitkennzahlen je Prozess für /admin/system (Concurrency-Audit, Paket 0).

Ein Ticker-Task misst alle SAMPLE_SECONDS, um wie viel sich sein eigenes ``asyncio.sleep``
verspätet - das ist die Event-Loop-Verzögerung, die jeder Request und jede WebSocket dieses
Workers spürt. Dazu die Belegung des SQLAlchemy-Pools und des anyio-Threadpools (sync-Routen)
sowie die Warteschlange des asyncio-Default-Executors (Hintergrund-Ticks, WebSocket-DB-Zugriffe).
Alle REPORT_SECONDS gehen die Spitzenwerte des Fensters über record_runtime_metrics (Migration
0148) an die Datenbank - über eine eigene, ungepoolte Verbindung mit kurzem Connect-Timeout,
damit die Meldung auch bei erschöpftem Pool ankommt und den Pool nie selbst belegt.

Prozesse ohne Event-Loop (job-worker, document-worker) melden über ``report_sync`` nur die
Pool-Werte.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import threading
import time
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool

_logger = logging.getLogger(__name__)

SAMPLE_SECONDS = 0.5
REPORT_SECONDS = 15.0
# Ab hier wird eine Verzögerung zusätzlich ins Log geschrieben (mit Prozess), unabhängig vom
# Monitoring - so lassen sich Ausreisser im Container-Log zeitlich zuordnen.
LOG_LAG_MS = 1000

_counters_lock = threading.Lock()
_counters: dict[str, int] = {"pool_timeouts": 0}


def count(name: str, amount: int = 1) -> None:
    """Zähler seit der letzten Meldung erhöhen (z. B. pool_timeouts aus dem 503-Handler)."""
    with _counters_lock:
        _counters[name] = _counters.get(name, 0) + amount


def observe_max(name: str, value: float) -> None:
    """Höchstwert seit der letzten Meldung (z. B. admission_wait_max_ms aus db_admission.py)."""
    with _counters_lock:
        _counters[name] = max(_counters.get(name, 0), round(value))


def _take_counters() -> dict[str, int]:
    with _counters_lock:
        taken = dict(_counters)
        for key in _counters:
            _counters[key] = 0
    return taken


def instance_name(process_kind: str) -> str:
    return f"{process_kind}:{socket.gethostname()}:{os.getpid()}"


def pool_usage(engine: Engine) -> tuple[int, int]:
    """(ausgecheckt, Kapazität) des QueuePools; NullPool o. ä.: (0, 0)."""
    pool = engine.pool
    checked_out = getattr(pool, "checkedout", None)
    size = getattr(pool, "size", None)
    if not callable(checked_out) or not callable(size):
        return 0, 0
    return int(checked_out()), int(size()) + max(0, int(getattr(pool, "_max_overflow", 0)))


class RuntimeReporter:
    def __init__(self, database_url: str, process_kind: str, *, connect_timeout: int = 3) -> None:
        self.process_kind = process_kind
        self.instance = instance_name(process_kind)
        self._engine = create_engine(
            database_url,
            poolclass=NullPool,
            hide_parameters=True,
            connect_args={"connect_timeout": connect_timeout, "application_name": f"hocx-{process_kind}-metrics"},
        )

    def report(self, metrics: dict[str, Any]) -> None:
        try:
            with self._engine.begin() as conn:
                conn.execute(
                    text("SELECT record_runtime_metrics(:instance, :kind, CAST(:metrics AS jsonb))"),
                    {"instance": self.instance, "kind": self.process_kind, "metrics": json.dumps(metrics)},
                )
        except Exception:
            # Best effort: fehlende Meldungen fallen in /admin/system als veraltete Instanz auf.
            _logger.warning("Laufzeitkennzahlen konnten nicht gemeldet werden", exc_info=True)


def _executor_queue(loop: asyncio.AbstractEventLoop) -> tuple[int, int]:
    executor = getattr(loop, "_default_executor", None)
    if executor is None:
        return 0, 0
    queue = getattr(executor, "_work_queue", None)
    threads = getattr(executor, "_threads", ())
    return (queue.qsize() if queue is not None else 0), len(threads)


async def run_monitor(reporter: RuntimeReporter, engine: Engine, *, sample_seconds: float = SAMPLE_SECONDS, report_seconds: float = REPORT_SECONDS) -> None:
    """Läuft für die Lebensdauer des Prozesses (lifespan)."""
    import anyio.to_thread

    loop = asyncio.get_running_loop()
    limiter = anyio.to_thread.current_default_thread_limiter()
    window: dict[str, float] = {}
    window_started = time.monotonic()
    while True:
        started = loop.time()
        await asyncio.sleep(sample_seconds)
        lag_ms = max(0.0, (loop.time() - started - sample_seconds) * 1000)
        if lag_ms >= LOG_LAG_MS:
            _logger.warning("Event-Loop von %s %d ms blockiert", reporter.instance, lag_ms)
        checked_out, capacity = pool_usage(engine)
        queued, executor_threads = _executor_queue(loop)
        sample = {
            "loop_lag_max_ms": lag_ms,
            "pool_checked_out_max": checked_out,
            "threadpool_busy_max": limiter.borrowed_tokens,
            "executor_queue_max": queued,
        }
        for key, value in sample.items():
            window[key] = max(window.get(key, 0.0), float(value))
        if time.monotonic() - window_started < report_seconds:
            continue
        metrics: dict[str, Any] = {key: round(value) for key, value in window.items()}
        metrics.update(
            pool_capacity=capacity,
            threadpool_total=int(limiter.total_tokens),
            executor_threads=executor_threads,
            window_seconds=round(time.monotonic() - window_started),
            **_take_counters(),
        )
        window, window_started = {}, time.monotonic()
        await asyncio.to_thread(reporter.report, metrics)


def report_sync(reporter: RuntimeReporter, engine: Engine, **extra: Any) -> None:
    """Für Prozesse ohne Event-Loop: Momentaufnahme des Pools plus eigene Werte."""
    checked_out, capacity = pool_usage(engine)
    reporter.report({"pool_checked_out_max": checked_out, "pool_capacity": capacity, **_take_counters(), **extra})
