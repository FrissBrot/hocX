"""Audit MAIN-BE-018: Der Checkout der Lock-Verbindung blockiert den Event-Loop nicht."""
import asyncio
import contextlib
import time
from types import SimpleNamespace

from app.core import background_loops as loops


class _SlowBegin:
    def __enter__(self):
        time.sleep(0.6)  # wie ein Pool-Checkout, der auf den Timeout wartet
        raise RuntimeError("Pool erschöpft")

    def __exit__(self, *exc):
        return False


def test_lock_checkout_runs_off_the_event_loop(monkeypatch):
    monkeypatch.setattr(loops, "engine", SimpleNamespace(begin=lambda: _SlowBegin()))
    monkeypatch.setattr(loops, "record_job_run", lambda *args, **kwargs: None)
    monkeypatch.setattr(loops, "record_system_error", lambda *args, **kwargs: None)
    monkeypatch.setattr(loops, "SessionLocal", lambda: contextlib.nullcontext(None))
    monkeypatch.setattr(loops.random, "uniform", lambda a, b: 0)

    async def main() -> float:
        started = time.monotonic()
        loop_task = asyncio.create_task(
            loops.run_advisory_locked_loop(name="export_cleanup", interval_seconds=3600, task=lambda db: None)
        )
        for _ in range(7):
            await asyncio.sleep(0.05)
        elapsed = time.monotonic() - started
        loop_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await loop_task
        return elapsed

    elapsed = asyncio.run(main())
    # Blockierte der Checkout den Loop, dauerten die sieben Mini-Sleeps (0.35 s) mindestens 0.6 s länger.
    assert elapsed < 0.55
