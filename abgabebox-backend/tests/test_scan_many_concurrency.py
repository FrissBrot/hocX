"""Regression tests for the critical audit finding (2026-08-27): app/scanner.py's scan_bytes()
is a plain blocking `def` (raw synchronous clamd socket, up to a 30s timeout) that used to be
called directly from routes/public.py's `async def upload()` - freezing the whole uvicorn worker
(every tenant, every other in-flight request on it) for the duration of each scan. The fix is
scanner.scan_many(), which runs each scan_bytes() call off the event loop via asyncio.to_thread,
with a small bounded concurrency instead of a fully sequential loop.

These tests exercise scan_many() directly (no HTTP layer, no real clamd/DB needed) by monkeypatching
scanner.scan_bytes to a fake that records which thread it ran on and how many calls were
in flight concurrently, mirroring the direct-function-call style of
test_tenant_upload_quota_lock.py rather than spinning up a full app/DB fixture.
"""
from __future__ import annotations

import asyncio
import threading
import time

from app import scanner


def _run(coro):
    """No async test support (pytest-asyncio/anyio) is set up in this repo - see
    test_upload_size_limits.py's docstring for the same rationale - so this just drives the
    coroutine under test to completion directly."""
    return asyncio.run(coro)


def test_scan_many_runs_scan_bytes_off_the_main_thread(monkeypatch):
    """scan_bytes() must run in a worker thread (asyncio.to_thread), never on the event loop's
    own thread - otherwise it still blocks the whole worker exactly like before the fix."""
    main_thread = threading.current_thread()
    seen_threads: list[threading.Thread] = []

    def fake_scan_bytes(content: bytes, *, host: str, port: int = 3310) -> str:
        seen_threads.append(threading.current_thread())
        return "clean"

    monkeypatch.setattr(scanner, "scan_bytes", fake_scan_bytes)

    results = _run(scanner.scan_many([b"a", b"b", b"c"], host="clamav-test"))

    assert results == ["clean", "clean", "clean"]
    assert len(seen_threads) == 3
    assert all(t is not main_thread for t in seen_threads), "scan_bytes ran on the event loop thread"


def test_scan_many_preserves_order_matching_input():
    """Results must line up positionally with the input list even though calls run
    concurrently and can finish out of order."""

    def fake_scan_bytes(content: bytes, *, host: str, port: int = 3310) -> str:
        # Sleep inversely to content length so later inputs finish first if run sequentially in
        # submission order - a real regression (results built in completion order, not input
        # order) would show up as a mismatch here.
        time.sleep(0.03 if content == b"first" else 0.0)
        return content.decode()

    import app.scanner as scanner_module

    original = scanner_module.scan_bytes
    scanner_module.scan_bytes = fake_scan_bytes
    try:
        results = _run(scanner_module.scan_many([b"first", b"second", b"third"], host="clamav-test"))
    finally:
        scanner_module.scan_bytes = original

    assert results == ["first", "second", "third"]


def test_scan_many_bounds_concurrency(monkeypatch):
    """Never more than _SCAN_CONCURRENCY scans in flight at once, even for a batch well above
    that - unbounded fan-out would open one clamd connection per file in a large batch."""
    in_flight = 0
    max_in_flight = 0
    lock = threading.Lock()

    def fake_scan_bytes(content: bytes, *, host: str, port: int = 3310) -> str:
        nonlocal in_flight, max_in_flight
        with lock:
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
        time.sleep(0.05)
        with lock:
            in_flight -= 1
        return "clean"

    monkeypatch.setattr(scanner, "scan_bytes", fake_scan_bytes)

    contents = [b"x"] * (scanner._SCAN_CONCURRENCY * 3)
    results = _run(scanner.scan_many(contents, host="clamav-test"))

    assert results == ["clean"] * len(contents)
    assert max_in_flight <= scanner._SCAN_CONCURRENCY
    assert max_in_flight > 1, "test is not actually exercising any concurrency"
