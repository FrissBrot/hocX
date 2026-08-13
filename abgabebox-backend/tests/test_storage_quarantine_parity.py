"""Closes the parity gap flagged by the 2026-08-12 audit (niedrig): the quarantine ->
regular-storage path transform is deliberately duplicated (not shared as a package - see
move_from_quarantine's own docstring) between this backend and
backend/app/services/submission_service.py::_move_from_quarantine, but only the main backend's
copy was pinned against the shared contract in
backend/tests/fixtures/quarantine_path_parity.json (see
backend/tests/test_submission_service_quarantine_parity.py) - this copy had to be checked by
hand, since abgabebox-backend had no pytest harness at the time that fixture was written. It has
one now (see test_upload_size_limits.py), so this closes the gap the fixture's own _comment asks
for.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.config import settings
from app.storage import move_from_quarantine

FIXTURE_PATH = Path(__file__).resolve().parents[2] / "backend" / "tests" / "fixtures" / "quarantine_path_parity.json"


def test_move_from_quarantine_matches_shared_contract(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    cases = json.loads(FIXTURE_PATH.read_text())["cases"]

    for case in cases:
        quarantine_rel_path = case["input"]
        source = tmp_path / quarantine_rel_path
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"content")

        result = move_from_quarantine(quarantine_rel_path)

        assert result == case["expected"]
        assert (tmp_path / result).read_bytes() == b"content"
        assert not source.exists()
