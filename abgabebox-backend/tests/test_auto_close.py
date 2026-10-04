"""submission_assignment.auto_close: ob upload() nach einer Abgabe zusaetzlich eine
status='closed'-Zeile schreibt (Migration 0099_submission_auto_close). Testet den Helper direkt,
wie test_max_files_per_request.py - die volle upload()-Route braucht DB-Fixtures, die diese
Suite nicht aufsetzt.
"""
from __future__ import annotations

from app.routes.public import _closes_after_upload


def _assignment(auto_close: str | None, max_files: int | None = 3) -> dict:
    return {"auto_close": auto_close, "max_files_per_element": max_files}


def test_never_does_not_close():
    assert _closes_after_upload(_assignment("never"), files_after_upload=99) is False


def test_missing_value_behaves_like_never():
    assert _closes_after_upload(_assignment(None), files_after_upload=3) is False
    assert _closes_after_upload({"max_files_per_element": 3}, files_after_upload=3) is False


def test_first_upload_always_closes():
    assert _closes_after_upload(_assignment("first_upload"), files_after_upload=1) is True
    assert _closes_after_upload(_assignment("first_upload", None), files_after_upload=1) is True


def test_max_files_closes_only_once_reached():
    assert _closes_after_upload(_assignment("max_files", 3), files_after_upload=2) is False
    assert _closes_after_upload(_assignment("max_files", 3), files_after_upload=3) is True


def test_max_files_without_maximum_never_closes():
    assert _closes_after_upload(_assignment("max_files", None), files_after_upload=1000) is False
