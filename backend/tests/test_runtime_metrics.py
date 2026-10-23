"""Laufzeitkennzahlen (Concurrency-Audit Paket 0): Meldung über record_runtime_metrics und die
Auswertung in /admin/system."""

import asyncio
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.pool import QueuePool

from app.core import runtime_metrics
from app.services import system_health_service


def _report(db, instance: str, metrics: dict, *, age_seconds: int = 0) -> None:
    db.execute(
        text("SELECT record_runtime_metrics(:i, 'backend', CAST(:m AS jsonb))"),
        {"i": instance, "m": json.dumps(metrics)},
    )
    if age_seconds:
        db.execute(
            text("UPDATE system_runtime_metric SET reported_at = NOW() - make_interval(secs => :s) WHERE instance = :i"),
            {"s": age_seconds, "i": instance},
        )


def test_runtime_check_is_unknown_without_reports(db):
    db.execute(text("DELETE FROM system_runtime_metric"))
    check = system_health_service._check_runtime(db, datetime.now(timezone.utc))
    assert check.status == "unknown"


def test_runtime_check_flags_blocked_loop_and_full_pool(db):
    db.execute(text("DELETE FROM system_runtime_metric"))
    _report(db, "backend:a:1", {"loop_lag_max_ms": 12, "pool_checked_out_max": 3, "pool_capacity": 15, "threadpool_busy_max": 2, "threadpool_total": 40})
    now = datetime.now(timezone.utc) + timedelta(seconds=1)
    assert system_health_service._check_runtime(db, now).status == "ok"

    _report(db, "backend:a:2", {"loop_lag_max_ms": 30000, "pool_checked_out_max": 15, "pool_capacity": 15, "pool_timeouts": 4})
    check = system_health_service._check_runtime(db, now)
    assert check.status == "critical"
    assert check.params["maxLagMs"] == 30000
    assert check.params["poolPeakPercent"] == 100
    assert check.params["poolTimeouts"] == 4


def test_runtime_check_ignores_stale_instances(db):
    db.execute(text("DELETE FROM system_runtime_metric"))
    _report(db, "backend:old:9", {"loop_lag_max_ms": 50000}, age_seconds=600)
    assert system_health_service._check_runtime(db, datetime.now(timezone.utc)).status == "unknown"


def test_record_runtime_metrics_rejects_bad_instance_names(db):
    import pytest
    from sqlalchemy.exc import DBAPIError

    with pytest.raises(DBAPIError):
        with db.begin_nested():
            _report(db, "bad name; drop", {})


def test_pool_usage_reports_capacity_including_overflow():
    engine = create_engine("postgresql+psycopg://u:p@localhost/x", poolclass=QueuePool, pool_size=5, max_overflow=10)
    assert runtime_metrics.pool_usage(engine) == (0, 15)


def test_monitor_reports_loop_lag(monkeypatch):
    reported: list[dict] = []

    class FakeReporter:
        instance = "backend:test:1"

        def report(self, metrics):
            reported.append(metrics)

    engine = create_engine("postgresql+psycopg://u:p@localhost/x", pool_size=5, max_overflow=10)

    async def scenario():
        task = asyncio.create_task(runtime_metrics.run_monitor(FakeReporter(), engine, sample_seconds=0.05, report_seconds=0.3))
        await asyncio.sleep(0.1)
        import time

        time.sleep(0.4)  # blockiert den Event-Loop wie ein synchroner DB-Aufruf
        await asyncio.sleep(0.5)
        task.cancel()

    asyncio.run(scenario())
    assert reported
    assert max(item["loop_lag_max_ms"] for item in reported) >= 300
    assert reported[0]["pool_capacity"] == 15
