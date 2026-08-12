"""Regression tests for H11 (2026-08-12 audit): the public Abgabebox upload endpoint had no
size limit anywhere before `content = await upload_file.read()` unconditionally buffered the
whole request body into memory. The real fix is two-layered:

  1. Traefik's abgabebox-upload-body-limit middleware (docker-compose.yml) rejects an
     oversized request before it ever reaches a backend worker - that layer can't be exercised
     from a Python test (no Traefik running here), so instead this file pins that its configured
     number never silently drifts from the application-level constant it's supposed to mirror.
  2. routes/public.py's _read_upload_within_limit(), used for every uploaded file instead of an
     unconditional .read(), which this file tests directly.

This is the first test file for abgabebox-backend, which previously had no pytest harness at
all (see backend/tests/test_submission_service_quarantine_parity.py's docstring) - hence the new
requirements-dev.txt alongside this directory.
"""
from __future__ import annotations

import asyncio
import io
import re
from pathlib import Path

from starlette.datastructures import UploadFile

from app.routes.public import MAX_UPLOAD_REQUEST_BYTES, _read_upload_within_limit

COMPOSE_PATH = Path(__file__).resolve().parents[2] / "docker-compose.yml"


def _run(coro):
    """No async test support (pytest-asyncio/anyio) is set up anywhere in this repo yet (grepped
    both backend/tests and here - no existing async test to follow a convention from), so this
    just drives the one coroutine under test to completion directly instead of introducing a new
    plugin/config for a single helper function."""
    return asyncio.run(coro)


def test_read_upload_within_limit_rejects_oversized_file_with_known_size():
    """Multipart-parsed uploads arrive with `.size` already populated (see the function's
    docstring) - a file over the limit must be rejected without needing a second full read."""
    data = b"x" * 2000
    upload = UploadFile(file=io.BytesIO(data), size=len(data), filename="big.pdf")

    result = _run(_read_upload_within_limit(upload, max_bytes=1000))

    assert result is None


def test_read_upload_within_limit_rejects_oversized_file_with_unknown_size():
    """Falls back to reading-then-measuring when `.size` isn't available (e.g. constructed
    without it, as can happen outside the normal multipart-parsing path) - must still reject."""
    data = b"x" * 2000
    upload = UploadFile(file=io.BytesIO(data), filename="big.pdf")  # size defaults to None

    result = _run(_read_upload_within_limit(upload, max_bytes=1000))

    assert result is None


def test_read_upload_within_limit_accepts_file_within_limit():
    data = b"y" * 500
    upload = UploadFile(file=io.BytesIO(data), size=len(data), filename="small.pdf")

    result = _run(_read_upload_within_limit(upload, max_bytes=1000))

    assert result == data


def test_read_upload_within_limit_accepts_file_exactly_at_limit():
    data = b"z" * 1000
    upload = UploadFile(file=io.BytesIO(data), size=len(data), filename="exact.pdf")

    result = _run(_read_upload_within_limit(upload, max_bytes=1000))

    assert result == data


def test_max_upload_request_bytes_matches_traefik_body_limit_label():
    """Config-drift guard: the Traefik maxRequestBodyBytes label in docker-compose.yml
    (abgabebox-upload-body-limit) is meant to enforce the exact same ceiling as
    MAX_UPLOAD_REQUEST_BYTES here, one layer earlier - if either number changes without the
    other, the two defenses silently disagree about the real limit. Plain text search (not a
    YAML parse) deliberately, so this test needs no extra dependency beyond what's already
    installed."""
    compose_text = COMPOSE_PATH.read_text()
    match = re.search(
        r"traefik\.http\.middlewares\.abgabebox-upload-body-limit\.buffering\.maxRequestBodyBytes=(\d+)",
        compose_text,
    )
    assert match is not None, "abgabebox-upload-body-limit maxRequestBodyBytes label not found in docker-compose.yml"
    assert int(match.group(1)) == MAX_UPLOAD_REQUEST_BYTES
