"""Regression tests for the critical audit finding (2026-08-27): before this fix, a tenant's
assignment.max_files_per_element may legitimately be None ("unbegrenzt Dateien"), and in that
case there was no application-level cap at all on how many files a single multipart upload
request could contain - only Starlette's own default (1000 files/request) stood in the way,
each scanned sequentially through a blocking clamd call with up to a 30s timeout per file.

app/routes/public.py's _exceeds_max_files_per_request() is the new hard ceiling, checked before
any file in the request is read or scanned, independent of max_files_per_element. This tests
that helper directly (same style as test_upload_size_limits.py's _read_upload_within_limit
tests) rather than the full upload() route, which needs a tenant/assignment/DB fixture this
suite doesn't set up.
"""
from __future__ import annotations

from app.config import settings
from app.routes.public import _exceeds_max_files_per_request


def test_exceeds_max_files_per_request_false_within_limit():
    assert _exceeds_max_files_per_request(settings.max_files_per_upload_request) is False


def test_exceeds_max_files_per_request_true_over_limit():
    assert _exceeds_max_files_per_request(settings.max_files_per_upload_request + 1) is True


def test_exceeds_max_files_per_request_is_independent_of_a_zero_or_small_request():
    assert _exceeds_max_files_per_request(0) is False
    assert _exceeds_max_files_per_request(1) is False


def test_exceeds_max_files_per_request_respects_configured_ceiling(monkeypatch):
    """The cap must actually come from settings (so ABGABEBOX_MAX_FILES_PER_UPLOAD_REQUEST can
    tune it) rather than a hardcoded number baked into the check."""
    monkeypatch.setattr(settings, "max_files_per_upload_request", 3)

    assert _exceeds_max_files_per_request(3) is False
    assert _exceeds_max_files_per_request(4) is True


def test_max_files_per_upload_request_has_a_sane_default_ceiling():
    """Guards against someone accidentally setting this to something absurd (e.g. 100000,
    which would defeat the point of the cap) or to unlimited."""
    assert 0 < settings.max_files_per_upload_request <= 200
