"""Locks the quarantine->regular-storage path contract that submission_service._move_from_quarantine
shares, by design, with abgabebox-backend/app/storage.py::move_from_quarantine (see audit finding
C-Niedrig-3: the two services intentionally duplicate this logic instead of sharing a package, to
keep the public-facing Abgabebox process's dependency surface isolated from the main backend - but
that means nothing catches the two copies drifting apart. This test pins backend's copy against the
shared fixture in tests/fixtures/quarantine_path_parity.json; abgabebox-backend has no pytest harness
yet, so its copy still has to be checked by hand against the same fixture until one exists."""
from __future__ import annotations

import json
from pathlib import Path

from app.services.submission_service import _move_from_quarantine

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "quarantine_path_parity.json"


def test_move_from_quarantine_matches_shared_contract(tmp_path):
    cases = json.loads(FIXTURE_PATH.read_text())["cases"]
    for case in cases:
        quarantine_rel_path = case["input"]
        source = tmp_path / quarantine_rel_path
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"content")

        result = _move_from_quarantine(quarantine_rel_path, str(tmp_path))

        assert result == case["expected"]
        assert (tmp_path / result).read_bytes() == b"content"
        assert not source.exists()
