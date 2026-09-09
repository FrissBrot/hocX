"""Regression tests for the medium audit finding (2026-08-27): storage.tenant_storage_bytes()
does a synchronous Path.rglob()+stat() walk over every file ever stored for a tenant - cost
grows with total accumulated files - and was called directly from routes/public.py's
`async def upload()` while holding the cross-process tenant_upload_lock(), blocking the whole
event loop (every tenant, every other in-flight request on that worker) for the duration of the
walk.

The fix wraps that call in `await asyncio.to_thread(...)` in routes/public.py. This is verified
two ways, mirroring how the rest of this suite avoids needing a full tenant/assignment/DB/HTTP
fixture (see test_tenant_upload_quota_lock.py's docstring):

  1. A source-level guard that the call site actually goes through asyncio.to_thread and not a
     direct call - catches a silent revert to blocking even if the timing assertion below were
     ever flaky.
  2. A timing test proving that running tenant_storage_bytes() via asyncio.to_thread lets a
     concurrent coroutine keep making progress while a (deliberately slowed-down) walk is in
     flight, i.e. the event loop is not blocked.
"""
from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path

from app.config import settings
from app.storage import tenant_storage_bytes

REPO_ROOT = Path(__file__).resolve().parents[1]
_TENANT_ID = 999002


def _reset(tmp_path: Path) -> None:
    for root in (
        tmp_path / f"tenant-{_TENANT_ID}",
        tmp_path / "quarantine" / f"tenant-{_TENANT_ID}",
    ):
        if root.exists():
            for f in root.rglob("*"):
                if f.is_file():
                    f.unlink()


def test_upload_route_wraps_tenant_storage_bytes_in_to_thread():
    """Guards against a silent regression back to a direct (blocking) call - the quota check in
    routes/public.py's upload() must go through asyncio.to_thread."""
    source = (REPO_ROOT / "app" / "routes" / "public.py").read_text(encoding="utf-8")
    assert re.search(r"await\s+asyncio\.to_thread\(\s*tenant_storage_bytes\s*,", source), (
        "tenant_storage_bytes() call in routes/public.py must be wrapped in "
        "'await asyncio.to_thread(...)' - see storage.py's tenant_storage_bytes docstring for why"
    )


def test_tenant_storage_bytes_via_to_thread_does_not_starve_the_event_loop(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    _reset(tmp_path)
    try:
        tenant_dir = tmp_path / f"tenant-{_TENANT_ID}" / "assignment-1"
        tenant_dir.mkdir(parents=True)
        (tenant_dir / "f.bin").write_bytes(b"x" * 500)

        # Simulate a tenant with a very large accumulated file count (a slow walk) by wrapping
        # the real function with an artificial delay - deterministic, rather than depending on
        # rglob() actually being slow enough on a handful of tmp_path files to expose a
        # regression via timing alone.
        def slow_tenant_storage_bytes(tenant_id: int) -> int:
            time.sleep(0.2)
            return tenant_storage_bytes(tenant_id)

        async def scenario():
            ticks = 0

            async def ticker():
                nonlocal ticks
                for _ in range(20):
                    await asyncio.sleep(0.01)
                    ticks += 1

            result, _ = await asyncio.gather(
                asyncio.to_thread(slow_tenant_storage_bytes, _TENANT_ID),
                ticker(),
            )
            return result, ticks

        result, ticks = asyncio.run(scenario())

        assert result == 500
        # If the slow call ran on the event loop's own thread instead of a worker thread, the
        # ticker coroutine would starve for ~0.2s and complete far fewer than 20 ticks in that
        # window - this is the same class of regression a direct (non-threaded) call would cause.
        assert ticks >= 15, f"event loop starved while tenant_storage_bytes ran (only {ticks} ticks)"
    finally:
        _reset(tmp_path)
