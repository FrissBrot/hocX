"""Regression test for a real bug (found 2026-09-10): cycle_snapshot_loop silently shared
its Postgres advisory-lock id with protocol_image_rescan_loop (copy-paste from that loop's
block, the lock id was never changed) - both loops run concurrently in the same worker
process, so whichever one won the lock in a given tick silently starved the other for that
tick instead of both doing their sweep. A plain code review easily misses this (the two
loops aren't adjacent in the file), so this asserts the invariant statically instead."""

import re
from pathlib import Path

MAIN_PY = Path(__file__).resolve().parents[1] / "app" / "main.py"


def test_every_advisory_lock_id_in_main_is_unique():
    source = MAIN_PY.read_text(encoding="utf-8")
    lock_ids = re.findall(r"pg_try_advisory_lock\((\d+)\)", source)
    assert len(lock_ids) >= 2, "expected to find the periodic background loops' advisory locks"
    duplicates = {lock_id for lock_id in lock_ids if lock_ids.count(lock_id) > 1}
    assert not duplicates, f"advisory lock id(s) used by more than one loop: {sorted(duplicates)}"
