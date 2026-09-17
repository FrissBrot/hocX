"""Regression test for a real bug (found 2026-09-10): cycle_snapshot_loop silently shared
its Postgres advisory-lock id with protocol_image_rescan_loop (copy-paste from that loop's
block, the lock id was never changed) - both loops run concurrently in the same worker
process, so whichever one won the lock in a given tick silently starved the other for that
tick instead of both doing their sweep. A plain code review easily misses this (the two
loops aren't adjacent in the file).

Every periodic loop's lock id now lives in one place (BACKGROUND_LOCK_IDS, see
app.core.background_loops) instead of being a literal copy-pasted into each loop's own
pg_try_advisory_lock(...) call - that module already asserts the dict's values are unique at
import time, so a repeat there fails immediately rather than silently in production. This
test is a second, explicit regression check for the same invariant, plus a check on the two
remaining one-shot startup locks in main.py (ensure_startup_seed_data,
ensure_default_document_templates - not periodic loops, so not part of the ledger) to make
sure neither of those literal ids collides with a periodic loop's either."""

import re
from pathlib import Path

from app.core.background_loops import BACKGROUND_LOCK_IDS

MAIN_PY = Path(__file__).resolve().parents[1] / "app" / "main.py"


def test_background_lock_ids_are_unique():
    values = list(BACKGROUND_LOCK_IDS.values())
    duplicates = {value for value in values if values.count(value) > 1}
    assert not duplicates, f"BACKGROUND_LOCK_IDS has a lock id shared by more than one loop: {sorted(duplicates)}"


def test_one_shot_startup_locks_in_main_do_not_collide_with_a_periodic_loop_or_each_other():
    source = MAIN_PY.read_text(encoding="utf-8")
    literal_ids = [int(match) for match in re.findall(r"pg_(?:try_)?advisory_lock\((\d+)\)", source)]
    assert literal_ids, "expected to find main.py's one-shot startup advisory locks"

    duplicates = {lock_id for lock_id in literal_ids if literal_ids.count(lock_id) > 1}
    assert not duplicates, f"one-shot startup lock id(s) used more than once in main.py: {sorted(duplicates)}"

    overlap = set(literal_ids) & set(BACKGROUND_LOCK_IDS.values())
    assert not overlap, f"main.py's one-shot startup lock id(s) collide with a periodic loop's: {sorted(overlap)}"


def test_every_background_lock_id_key_referenced_in_main_is_defined():
    """Regression test for a real bug (found 2026-09-17 audit): three loops
    (photo_analysis_auto_queue_loop/photo_quality_backfill_loop/photo_album_sync_loop) read
    BACKGROUND_LOCK_IDS["photo_analysis_auto_queue"] etc. from the moment they were written,
    but the three matching dict entries were never added - each loop raised KeyError on its
    very first tick, forever, with nothing but a swallowed asyncio warning to show for it.
    Uniqueness-of-values (test_background_lock_ids_are_unique) doesn't catch a *missing* key,
    only a duplicate one, so this checks the other direction: every symbolic key main.py
    subscripts BACKGROUND_LOCK_IDS with must actually be defined."""
    source = MAIN_PY.read_text(encoding="utf-8")
    referenced_keys = set(re.findall(r'BACKGROUND_LOCK_IDS\["([^"]+)"\]', source))
    assert referenced_keys, "expected to find symbolic BACKGROUND_LOCK_IDS[...] lookups in main.py"

    missing = referenced_keys - set(BACKGROUND_LOCK_IDS.keys())
    assert not missing, f"main.py references BACKGROUND_LOCK_IDS key(s) not defined in the dict: {sorted(missing)}"
