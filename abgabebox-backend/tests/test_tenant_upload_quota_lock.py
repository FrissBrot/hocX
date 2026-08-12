"""Regression tests for H12 (2026-08-12 audit): tenant_storage_bytes() walks the filesystem
with no locking before an upload is written, so two near-simultaneous uploads for the same
tenant could both observe "under quota" and together exceed it (TOCTOU). The fix wraps the
check-then-write sequence in routes/public.py's upload() in db.tenant_upload_lock(), a per-tenant
Postgres advisory lock (chosen over an in-process asyncio.Lock because this service runs
`--workers 2`, i.e. two separate OS processes - see docker-compose.yml and db.py's docstring).

These tests exercise the lock and the exact check-then-write pattern the route uses directly
against real files under settings.storage_root (no HTTP layer, no captcha/ClamAV/DB fixtures
needed - tenant_storage_bytes/save_to_quarantine only need a tenant_id and the filesystem), using
a throwaway synthetic tenant id that nothing else in this suite touches.
"""
from __future__ import annotations

import shutil
import threading
import time
from pathlib import Path

from app.config import settings
from app.db import tenant_upload_lock
from app.storage import save_to_quarantine, tenant_storage_bytes

# Arbitrary, high enough to not collide with any real or other-test tenant id.
_TENANT_ID = 999001


def _reset():
    for root in (
        Path(settings.storage_root) / f"tenant-{_TENANT_ID}",
        Path(settings.storage_root) / "quarantine" / f"tenant-{_TENANT_ID}",
    ):
        shutil.rmtree(root, ignore_errors=True)


def _check_then_write(quota_bytes: int, content: bytes, results: dict, key: str) -> None:
    """Same shape as the critical section in routes/public.py's upload(): read current usage,
    reject if it plus the incoming bytes would exceed quota, otherwise write. The sleep widens
    the check-to-write window (real request handling has a scan step in between, see upload()) so
    two barrier-released threads reliably overlap inside it instead of only occasionally
    happening to - without this, manually removing tenant_upload_lock() around this call made the
    test below fail about 4 times out of 5, not consistently, which is not a trustworthy
    regression guard."""
    current = tenant_storage_bytes(_TENANT_ID)
    time.sleep(0.05)
    if current + len(content) > quota_bytes:
        results[key] = "rejected"
        return
    save_to_quarantine(content, tenant_id=_TENANT_ID, assignment_id=1, suffix=".pdf")
    results[key] = "accepted"


def test_locked_concurrent_uploads_that_would_together_exceed_quota_are_serialized():
    """Two uploads, each individually within a synthetic tiny quota, that would together exceed
    it if both were accepted. With the per-tenant lock around check-then-write, exactly one must
    be accepted and the tenant's on-disk usage must never exceed the quota."""
    _reset()
    try:
        quota_bytes = 150
        chunk = b"x" * 100  # 100 <= 150 alone; 100 + 100 = 200 > 150 together

        results: dict[str, str] = {}
        barrier = threading.Barrier(2)

        def worker(key: str) -> None:
            barrier.wait(timeout=5)
            with tenant_upload_lock(_TENANT_ID):
                _check_then_write(quota_bytes, chunk, results, key)

        threads = [threading.Thread(target=worker, args=(k,)) for k in ("a", "b")]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        accepted = [v for v in results.values() if v == "accepted"]
        assert len(accepted) == 1, f"expected exactly one upload accepted under quota, got: {results}"
        assert tenant_storage_bytes(_TENANT_ID) <= quota_bytes
    finally:
        _reset()


def test_tenant_upload_lock_is_scoped_per_tenant_not_global():
    """Two different tenants must not block each other - a global lock would needlessly
    serialize unrelated tenants' uploads and could look like it "worked" in the test above for
    the wrong reason (accidentally serializing everything, not just same-tenant access). Uses
    Events with short timeouts throughout (never an unbounded wait) so a regression to a global
    lock fails this test quickly instead of hanging it forever."""
    other_tenant_id = _TENANT_ID + 1
    order: list[str] = []
    a_acquired = threading.Event()
    release_a = threading.Event()
    b_acquired = threading.Event()

    def hold_a():
        with tenant_upload_lock(_TENANT_ID):
            order.append("a-acquired")
            a_acquired.set()
            release_a.wait(timeout=5)
        order.append("a-released")

    def take_b():
        with tenant_upload_lock(other_tenant_id):
            order.append("b-acquired")
            b_acquired.set()

    t_a = threading.Thread(target=hold_a)
    t_a.start()
    assert a_acquired.wait(timeout=5), "tenant A lock never acquired"

    t_b = threading.Thread(target=take_b)
    t_b.start()
    # A different tenant's lock must succeed quickly even while A's is held - well under how
    # long it would have to wait if this were (incorrectly) a single global lock.
    acquired_promptly = b_acquired.wait(timeout=2)
    release_a.set()
    t_a.join(timeout=5)
    t_b.join(timeout=5)

    assert acquired_promptly, "tenant B's lock blocked on tenant A's lock - locks are not per-tenant"
    assert order.index("b-acquired") < order.index("a-released")
