"""Regression tests for the audit finding (2026-08-27) that upgraded CAPTCHA's fail-open
behavior from an informational note to a hard requirement: when neither FRIENDLY_CAPTCHA_SITEKEY
nor FRIENDLY_CAPTCHA_API_KEY is configured, that's fine and intentional ONLY on a genuine local
dev/test stack (uploads may proceed without captcha there, same as before). In PRODUCTION,
captcha being unusable for ANY reason - both keys missing, or FriendlyCaptcha's own API
erroring/timing out at verify time - must reject the upload (fail closed), never silently allow
it through.

app/config.py's new `environment` setting (ABGABEBOX_ENVIRONMENT, default "production" - unset
is treated as production-like, i.e. fail closed by default) is what distinguishes the two cases;
app/captcha.py's _skip_captcha_when_unconfigured() and verify_captcha()'s except clause are the
two enforcement points. These tests call captcha.py's functions directly (no HTTP layer, no real
FriendlyCaptcha account or DB needed), same style as the rest of this suite.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

from app import captcha
from app.config import settings


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _reset_captcha_config(monkeypatch):
    """Every test starts from "nothing configured" and overrides only what it needs -
    otherwise leftover state from one test (e.g. a monkeypatched sitekey) could leak into the
    next via the shared `settings` singleton."""
    monkeypatch.setattr(settings, "friendly_captcha_sitekey", "")
    monkeypatch.setattr(settings, "friendly_captcha_api_key", "")
    monkeypatch.setattr(settings, "environment", "production")


# --- Neither key configured: dev/test skips, production rejects -----------------------------


def test_dev_environment_with_no_keys_configured_skips_captcha_session_check(monkeypatch):
    monkeypatch.setattr(settings, "environment", "development")

    assert captcha.verify_captcha_session_token("anything-or-empty", "acme", "hw1", "e1") is True


def test_test_environment_with_no_keys_configured_skips_captcha_session_check(monkeypatch):
    monkeypatch.setattr(settings, "environment", "test")

    assert captcha.verify_captcha_session_token("anything-or-empty", "acme", "hw1", "e1") is True


def test_dev_environment_with_no_keys_configured_lets_verify_captcha_pass(monkeypatch):
    monkeypatch.setattr(settings, "environment", "development")

    assert _run(captcha.verify_captcha("")) is True


def test_production_with_no_keys_configured_rejects_captcha_session_check():
    """The core fix: what used to silently return True (skip) now must return False (reject)
    once ABGABEBOX_ENVIRONMENT is production (or, since production is the default, whenever it's
    simply unset)."""
    assert captcha.verify_captcha_session_token("anything-or-empty", "acme", "hw1", "e1") is False


def test_production_with_no_keys_configured_rejects_verify_captcha():
    assert _run(captcha.verify_captcha("some-solution")) is False


def test_unset_environment_defaults_to_production_like_fail_closed(monkeypatch):
    """Safety-by-default: an operator who forgets to set ABGABEBOX_ENVIRONMENT at all must get
    the safe (fail-closed) behavior, not accidentally the permissive dev/test one."""
    monkeypatch.setattr(settings, "environment", "")

    assert captcha.verify_captcha_session_token("anything-or-empty", "acme", "hw1", "e1") is False


def test_unrecognized_environment_value_fails_closed(monkeypatch):
    monkeypatch.setattr(settings, "environment", "staging-typo")

    assert captcha.verify_captcha_session_token("anything-or-empty", "acme", "hw1", "e1") is False


# --- FriendlyCaptcha API failure at verify time: must fail closed regardless of environment ---


class _RaisingAsyncClient:
    """Stand-in for httpx.AsyncClient whose POST simulates FriendlyCaptcha's own API being
    unreachable (network error/timeout) - not a missing-config case, an actual runtime failure
    of the third-party service."""

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self) -> "_RaisingAsyncClient":
        return self

    async def __aexit__(self, *exc_info) -> bool:
        return False

    async def post(self, *args, **kwargs):
        raise httpx.ConnectError("simulated FriendlyCaptcha outage")


def test_production_rejects_upload_when_friendly_captcha_api_call_fails(monkeypatch):
    """Both keys ARE configured (captcha is meant to be active) but the actual verify call to
    FriendlyCaptcha errors out - must still fail closed, not assume the solution was valid."""
    monkeypatch.setattr(settings, "friendly_captcha_sitekey", "site-123")
    monkeypatch.setattr(settings, "friendly_captcha_api_key", "secret-456")
    monkeypatch.setattr(captcha.httpx, "AsyncClient", _RaisingAsyncClient)

    assert _run(captcha.verify_captcha("some-solution")) is False


def test_dev_environment_also_rejects_upload_when_friendly_captcha_api_call_fails(monkeypatch):
    """The API-failure fail-closed path is NOT environment-gated: real keys being configured
    means captcha is deliberately active even on a dev/test stack, so a broken API call there
    must reject too, not silently pass."""
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "friendly_captcha_sitekey", "site-123")
    monkeypatch.setattr(settings, "friendly_captcha_api_key", "secret-456")
    monkeypatch.setattr(captcha.httpx, "AsyncClient", _RaisingAsyncClient)

    assert _run(captcha.verify_captcha("some-solution")) is False


class _BadJsonAsyncClient:
    """Simulates a 200 response whose body isn't valid JSON - a different flavor of "the API
    call didn't actually tell us anything usable" than a network error, also must fail closed."""

    class _Response:
        status_code = 200

        def json(self):
            raise ValueError("not json")

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self) -> "_BadJsonAsyncClient":
        return self

    async def __aexit__(self, *exc_info) -> bool:
        return False

    async def post(self, *args, **kwargs):
        return self._Response()


def test_production_rejects_upload_when_friendly_captcha_response_body_is_not_json(monkeypatch):
    monkeypatch.setattr(settings, "friendly_captcha_sitekey", "site-123")
    monkeypatch.setattr(settings, "friendly_captcha_api_key", "secret-456")
    monkeypatch.setattr(captcha.httpx, "AsyncClient", _BadJsonAsyncClient)

    assert _run(captcha.verify_captcha("some-solution")) is False


# --- Partial config (already-fixed 2026-08-25 case) stays fail-closed regardless of environment --


def test_partial_config_still_fails_closed_even_in_dev_environment(monkeypatch):
    """Exactly one key set is always a misconfiguration, never a deliberate "no captcha"
    choice - must stay fail-closed in every environment, not just production (audit finding
    2026-08-25, unaffected by the 2026-08-27 environment-awareness fix)."""
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "friendly_captcha_sitekey", "site-only")
    monkeypatch.setattr(settings, "friendly_captcha_api_key", "")

    assert captcha.verify_captcha_session_token("anything-or-empty", "acme", "hw1", "e1") is False
