"""Locks the quarantine->regular-storage path contract that submission_service._move_from_quarantine
shares, by design, with abgabebox-backend/app/storage.py::move_from_quarantine (see audit finding
C-Niedrig-3: the two services intentionally duplicate this logic instead of sharing a package, to
keep the public-facing Abgabebox process's dependency surface isolated from the main backend - but
that means nothing catches the two copies drifting apart. This test pins backend's copy against the
shared fixture in tests/fixtures/quarantine_path_parity.json; abgabebox-backend's copy is pinned
against the same fixture in abgabebox-backend/tests/test_storage_quarantine_parity.py."""
from __future__ import annotations

import json
from pathlib import Path

from app.services.submission_service import quarantine_target_key

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "quarantine_path_parity.json"


def test_move_from_quarantine_matches_shared_contract():
    # Der Pfad-Vertrag ist seit dem Objektspeicher eine reine Funktion; das Verschieben selbst
    # (Kopieren + Löschen mit Journal) testet tests/test_object_storage.py.
    cases = json.loads(FIXTURE_PATH.read_text())["cases"]
    for case in cases:
        assert quarantine_target_key(case["input"]) == case["expected"]
