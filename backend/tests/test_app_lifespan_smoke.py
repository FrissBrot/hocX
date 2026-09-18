"""Boots the real ASGI app - including its actual `lifespan()`, not a bare `FastAPI()`
stand-in with dependency overrides like every other route test in this suite (see
tests/test_permission_routes.py) - and lets each of the ten background loops in
app/main.py run its first tick for real.

Why this exists: every one of those ten loops is a bare `asyncio.create_task(...)` that
nothing ever awaits or inspects (see the `yield`/`.cancel()` pairs in `lifespan()`), so an
exception raised the instant a loop's coroutine starts running is only ever an asyncio
"Task exception was never retrieved" warning - never a failed test. That is exactly how
the 2026-09-17 audit's KeyError bug shipped and stayed invisible: three of the nine loops
referenced `BACKGROUND_LOCK_IDS["photo_analysis_auto_queue"]` /
`["photo_quality_backfill"]` / `["photo_album_sync"]`, three keys nobody had actually
added to that dict, so those loops raised `KeyError` on their very first statement, before
ever touching the database - permanently and silently killing the auto photo-album/
quality-backfill/auto-queue features. tests/test_main_advisory_locks.py now guards the
*dict* statically (every `BACKGROUND_LOCK_IDS[...]` reference in main.py has a matching
key), but a static regex scan can't catch every way a loop's startup could break (a typo'd
setting name, a bad import, ...) - only actually running the coroutines can. This test is
that: it fails if starting the app ever again leaves a loop dead on arrival.
"""

from __future__ import annotations

import asyncio

import app.main as main_module
from app.main import app, lifespan


def test_background_loops_start_without_crashing(monkeypatch):
    # This test's DB already carries the demo-seed identities every other test in this
    # suite runs against (see tests/conftest.py) - ensure_no_production_demo_data() exists
    # to stop exactly that combination in a real deployment (see its own dedicated
    # coverage in test_migration_demo_seed_safety.py) and would otherwise fail this test
    # for a reason that has nothing to do with what it's checking.
    monkeypatch.setattr(main_module, "ensure_no_production_demo_data", lambda: None)

    async def _boot_and_check() -> None:
        async with lifespan(app):
            # Every asyncio.create_task(...) call inside lifespan() (before its `yield`)
            # schedules onto *this* running loop - asyncio.all_tasks() from right here sees
            # them all, still pending (they haven't had a chance to run yet).
            tasks = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
            assert len(tasks) == 10, f"expected the 10 background loop tasks, found {len(tasks)}"

            # Give the event loop real wall-clock time to actually step each task once -
            # run_advisory_locked_loop (app/core/background_loops.py) does its first
            # gate-check/lock-acquire/task-call before its first sleep, so one tick already
            # happens here without waiting out any loop's real (minutes-scale) interval.
            await asyncio.sleep(2)

            # Checked *inside* the `with lifespan(...)` block, before shutdown cancels
            # every task - cancellation itself sets CancelledError as a task's exception,
            # which would otherwise be indistinguishable from a genuine startup crash.
            crashed = [
                (task.get_coro(), task.exception())
                for task in tasks
                if task.done()
            ]
            assert not crashed, f"background loop(s) crashed on startup: {crashed}"

    asyncio.run(_boot_and_check())
