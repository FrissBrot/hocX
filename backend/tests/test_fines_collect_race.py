"""Regression test for H13 (2026-08-12 audit): collect_fine() must lock the fine row with
SELECT ... FOR UPDATE so two near-simultaneous requests can't both observe status == "pending"
and each create a FinanceTransaction.

This deliberately does NOT use the shared `db` fixture from conftest.py: that fixture keeps a
test's writes on a single connection inside an outer transaction that's rolled back at teardown
(see its docstring), which is exactly the trick that makes a *genuine* cross-connection row lock
untestable - a second, independent connection can never see another transaction's uncommitted
rows. Real row-lock blocking requires two real connections/transactions, so this test opens its
own and cleans up explicitly afterwards (Tenant cascades to everything else via ON DELETE
CASCADE, see app/models/entities.py, so a single DELETE FROM tenant is enough).
"""
from __future__ import annotations

import threading
import time

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.db import engine
from app.models.entities import AttendanceFine
from app.repositories.fines_repository import FinesRepository
from tests.factories import make_finance_account, make_fine, make_protocol, make_template, make_tenant


def _make_race_fixture():
    conn = engine.connect()
    session = Session(bind=conn, autoflush=False, future=True)
    tenant = make_tenant(session, "Fines Race Tenant")
    template = make_template(session, tenant.id)
    protocol = make_protocol(session, tenant.id, template.id, protocol_number=f"RACE-{tenant.id}")
    account = make_finance_account(session, tenant.id)
    fine = make_fine(session, protocol.id, account.id)
    session.commit()
    ids = {"tenant_id": tenant.id, "protocol_id": protocol.id, "account_id": account.id, "fine_id": fine.id}
    session.close()
    conn.close()
    return ids


def _cleanup(tenant_id: int) -> None:
    conn = engine.connect()
    try:
        conn.execute(text("DELETE FROM tenant WHERE id = :tid"), {"tid": tenant_id})
        conn.commit()
    finally:
        conn.close()


def test_collect_fine_blocks_on_concurrent_holder_of_the_row_lock():
    """Sanity check that a row lock held by another in-flight collect_fine-like transaction
    really does serialize a subsequent collect_fine() call end-to-end (it can't return before
    the holder's transaction ends): a second connection holds SELECT ... FOR UPDATE on the fine
    row open for ~0.4s before releasing it unchanged; collect_fine() on a third connection must
    be observed to block for roughly that long before it can proceed.

    Note this alone would NOT catch a regression that drops with_for_update() from collect_fine
    itself - the eventual UPDATE that flush()/commit() issues when marking the fine "collected"
    also blocks on a held row lock even without an explicit locking SELECT. What specifically
    catches that regression is the Python-level "already collected?" status check racing ahead
    of the lock instead of behind it - see test_collect_fine_race_only_one_of_two_concurrent_
    callers_succeeds below, which fails with two successes (and a duplicate FinanceTransaction)
    if with_for_update() is removed, exactly reproducing H13."""
    ids = _make_race_fixture()
    fine_id = ids["fine_id"]
    hold_seconds = 0.4

    lock_acquired = threading.Event()
    release_lock = threading.Event()

    def holder():
        conn = engine.connect()
        session = Session(bind=conn, autoflush=False, future=True)
        try:
            session.execute(select(AttendanceFine).where(AttendanceFine.id == fine_id).with_for_update())
            lock_acquired.set()
            release_lock.wait(timeout=5)
            time.sleep(hold_seconds)
        finally:
            session.rollback()  # never modifies the row, just releases the lock
            session.close()
            conn.close()

    holder_thread = threading.Thread(target=holder)
    holder_thread.start()
    assert lock_acquired.wait(timeout=5), "holder thread never acquired the row lock"
    release_lock.set()

    conn = engine.connect()
    session = Session(bind=conn, autoflush=False, future=True)
    repo = FinesRepository()
    try:
        started = time.monotonic()
        result = repo.collect_fine(session, fine_id, tenant_id=ids["tenant_id"], actor_user_id=1)
        elapsed = time.monotonic() - started
    finally:
        session.close()
        conn.close()
        holder_thread.join(timeout=5)

    assert result is not None, "collect_fine should succeed once the competing lock is released"
    assert elapsed >= hold_seconds * 0.7, (
        f"collect_fine returned after only {elapsed:.2f}s - expected it to block on the "
        f"concurrently-held row lock for close to {hold_seconds}s (with_for_update() may be missing)"
    )

    _cleanup(ids["tenant_id"])


def test_collect_fine_race_only_one_of_two_concurrent_callers_succeeds():
    """Fires collect_fine() from two threads/connections at (as close to) the same instant as
    possible via a barrier. Exactly one must succeed and create the FinanceTransaction; the
    other must observe the now-"collected" status and return None - never both."""
    ids = _make_race_fixture()
    fine_id = ids["fine_id"]
    tenant_id = ids["tenant_id"]

    barrier = threading.Barrier(2)
    results: dict[str, object] = {}

    def worker(name: str):
        conn = engine.connect()
        session = Session(bind=conn, autoflush=False, future=True)
        repo = FinesRepository()
        try:
            barrier.wait(timeout=5)
            results[name] = repo.collect_fine(session, fine_id, tenant_id=tenant_id, actor_user_id=1)
        finally:
            session.close()
            conn.close()

    threads = [threading.Thread(target=worker, args=(name,)) for name in ("a", "b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    successes = [v for v in results.values() if v is not None]
    assert len(successes) == 1, f"expected exactly one collect_fine call to succeed, got: {results}"

    with engine.connect() as verify_conn:
        tx_count = verify_conn.execute(
            text("SELECT COUNT(*) FROM finance_transaction WHERE account_id = :aid"),
            {"aid": ids["account_id"]},
        ).scalar_one()
    assert tx_count == 1, f"expected exactly one FinanceTransaction, found {tx_count}"

    _cleanup(tenant_id)
