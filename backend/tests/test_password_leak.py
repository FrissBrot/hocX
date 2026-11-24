"""Leak-Prüfung neuer Passwörter (SEC-AUTH-015, app/core/password_leak.py) - ohne Netzzugriff.

HIBP wird gemockt (``urllib.request.urlopen``), Redis durch ein Wörterbuch ersetzt. Geprüft wird,
dass nur 5 Hex-Zeichen das System verlassen, Padding-Zeilen (Zählwert 0) nie zählen, der Rückfall
auf die lokale Liste greift und nie Passwort, Hash oder Suffix im Log landen.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
import socket
import urllib.error

import pytest
from fastapi import HTTPException

from app.core import password_leak
from app.core.config import settings
from app.core.password_policy import ensure_password_acceptable, evaluate_password


def _strong_password() -> str:
    # Zur Laufzeit erzeugt (SECURITY-RULES 5.1); so lange neu, bis die Stärkeregel erfüllt ist
    # (eine zufällige Folge wie «12345» oder «aaa» gälte als leicht zu erraten)
    while True:
        candidate = "Wald-" + secrets.token_hex(6) + "-Fluss!"
        if evaluate_password(candidate).acceptable:
            return candidate


def _split(password: str) -> tuple[str, str]:
    digest = hashlib.sha1(password.encode()).hexdigest().upper()  # noqa: S324 - HIBP-Format
    return digest[:5], digest[5:]


class _FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, object] = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value, ex=None):
        self.data[key] = value

    def hset(self, key, field, value):
        self.data.setdefault(key, {})[field] = value

    def hgetall(self, key):
        return self.data.get(key, {})

    def expire(self, key, seconds, nx=False):
        return True

    def incr(self, key):
        self.data[key] = int(self.data.get(key, 0)) + 1
        return self.data[key]


class _Response:
    def __init__(self, body: str, status: int = 200) -> None:
        self._body = body.encode()
        self.status = status

    def read(self, size: int = -1) -> bytes:
        chunk, self._body = (self._body, b"") if size < 0 else (self._body[:size], self._body[size:])
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def _range_body(entries: dict[str, int], padding: int = 50) -> str:
    lines = [f"{suffix}:{count}" for suffix, count in entries.items()]
    lines += [f"{secrets.token_hex(18)[:35].upper()}:0" for _ in range(padding)]
    return "\r\n".join(lines)


@pytest.fixture
def redis_fake(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(password_leak, "_redis", lambda: fake)
    return fake


@pytest.fixture
def hibp(monkeypatch, redis_fake):
    """Gemockte Range-API: ``hibp.ranges[prefix] = body``; ``hibp.calls`` hält die Requests."""

    class _Api:
        ranges: dict[str, str] = {}
        calls: list = []
        error: Exception | None = None

    api = _Api()
    api.ranges, api.calls, api.error = {}, [], None

    def fake_urlopen(request, timeout=None):
        api.calls.append((request.full_url, dict(request.header_items()), timeout))
        if api.error is not None:
            raise api.error
        prefix = request.full_url.rsplit("/", 1)[-1]
        return _Response(api.ranges.get(prefix, _range_body({})))

    monkeypatch.setattr(password_leak._opener, "open", fake_urlopen)
    monkeypatch.setattr(settings, "password_leak_check", "on")
    monkeypatch.setattr(settings, "password_leak_min_count", 1)
    return api


def test_hit_sends_only_the_five_char_prefix_with_padding_header(hibp, caplog):
    password = _strong_password()
    prefix, suffix = _split(password)
    hibp.ranges[prefix] = _range_body({suffix: 42})
    caplog.set_level(logging.DEBUG)
    result = password_leak.check_password(password)
    assert result == password_leak.LeakResult(leaked=True, source="hibp", count=42)
    url, headers, timeout = hibp.calls[0]
    assert url == f"https://api.pwnedpasswords.com/range/{prefix}"
    assert len(url.rsplit("/", 1)[-1]) == 5
    assert headers.get("Add-padding") == "true"
    # Eigener User-Agent ohne Personen- oder Projektdaten
    assert headers.get("User-agent") == "hocx-password-check"
    assert timeout == settings.password_leak_timeout_seconds
    # Weder Passwort noch Hash noch Suffix im Log
    assert password not in caplog.text and suffix not in caplog.text and prefix + suffix not in caplog.text


def test_no_hit_is_accepted(hibp):
    password = _strong_password()
    prefix, _suffix = _split(password)
    hibp.ranges[prefix] = _range_body({"0" * 35: 3})
    assert password_leak.check_password(password) == password_leak.LeakResult(leaked=False, source="hibp", count=0)


def test_padding_lines_with_count_zero_are_ignored(hibp):
    password = _strong_password()
    prefix, suffix = _split(password)
    # Ein Fülleintrag mit genau diesem Suffix zählt nicht als Treffer
    hibp.ranges[prefix] = _range_body({suffix: 0, "A" * 35: 7})
    assert password_leak.check_password(password).leaked is False


def test_threshold_is_configurable(hibp, monkeypatch):
    password = _strong_password()
    prefix, suffix = _split(password)
    hibp.ranges[prefix] = _range_body({suffix: 2})
    monkeypatch.setattr(settings, "password_leak_min_count", 3)
    assert password_leak.check_password(password).leaked is False
    monkeypatch.setattr(settings, "password_leak_min_count", 2)
    assert password_leak.check_password(password).leaked is True


def test_range_is_cached_per_prefix(hibp, redis_fake):
    password = _strong_password()
    prefix, suffix = _split(password)
    hibp.ranges[prefix] = _range_body({suffix: 5})
    assert password_leak.check_password(password).leaked
    assert password_leak.check_password(password).leaked
    assert len(hibp.calls) == 1
    # Schlüssel ohne Klartext-Präfix (HMAC)
    assert not any(prefix in key for key in redis_fake.data)
    cached = redis_fake.data[password_leak._cache_key(prefix)]
    # Im Cache nur echte Einträge (keine Fülleinträge), kein Passwort
    assert ":0" not in cached and password not in cached


@pytest.mark.parametrize("error", [socket.timeout("timed out"), urllib.error.URLError("down"), TimeoutError()])
def test_timeout_falls_back_to_the_local_list(hibp, redis_fake, error):
    hibp.error = error
    # Aus der lokalen Liste (SecLists, ab 12 Zeichen): bekannt -> abgelehnt
    leaked = password_leak.check_password("qwertyuiopasdfgh")
    assert leaked == password_leak.LeakResult(leaked=True, source="local")
    clean = password_leak.check_password(_strong_password())
    assert clean == password_leak.LeakResult(leaked=False, source="local")
    assert "last_failure" in redis_fake.data[password_leak.STATUS_KEY]


def test_broken_cache_entry_is_a_miss(hibp, redis_fake):
    password = _strong_password()
    prefix, suffix = _split(password)
    redis_fake.data[password_leak._cache_key(prefix)] = ""
    hibp.ranges[prefix] = _range_body({suffix: 4})
    assert password_leak.check_password(password).leaked is True
    assert len(hibp.calls) == 1


def test_redirects_are_never_followed():
    import urllib.request

    assert any(isinstance(handler, password_leak._NoRedirect) for handler in password_leak._opener.handlers)
    assert not any(type(handler) is urllib.request.HTTPRedirectHandler for handler in password_leak._opener.handlers)


def test_empty_or_broken_answer_counts_as_unavailable(hibp):
    hibp.ranges[_split("qwertyuiopasdfgh")[0]] = "kaputt"
    assert password_leak.check_password("qwertyuiopasdfgh").source == "local"


def test_local_only_never_calls_hibp(hibp, monkeypatch):
    monkeypatch.setattr(settings, "password_leak_check", "local-only")
    assert password_leak.check_password("qwertyuiopasdfgh").leaked is True
    assert password_leak.check_password(_strong_password()).leaked is False
    assert hibp.calls == []


def test_off_disables_the_check(hibp, monkeypatch):
    monkeypatch.setattr(settings, "password_leak_check", "off")
    assert password_leak.check_password("qwertyuiopasdfgh") == password_leak.LeakResult(leaked=False, source="none")
    assert hibp.calls == []


def test_without_hibp_and_local_list_the_password_is_accepted_and_counted(hibp, redis_fake, monkeypatch, caplog):
    hibp.error = urllib.error.URLError("down")
    monkeypatch.setattr(password_leak, "_local", password_leak._LocalList(password_leak.LIST_PATH.with_name("fehlt.bin")))
    caplog.set_level(logging.WARNING)
    assert password_leak.check_password("qwertyuiopasdfgh") == password_leak.LeakResult(leaked=False, source="none")
    assert redis_fake.data[password_leak.UNCHECKED_KEY] == 1
    assert "ungeprüft" in caplog.text and "qwertyuiopasdfgh" not in caplog.text
    status = password_leak.status()
    assert status["unchecked_24h"] == 1 and status["local_list"] is False


def test_local_list_is_compact_and_sorted():
    raw = password_leak.LIST_PATH.read_bytes()
    assert raw.startswith(b"HXLP1\n")
    local = password_leak._LocalList(password_leak.LIST_PATH)
    assert local.count > 50_000
    items = [local._item(i) for i in range(0, local.count, 997)]
    assert items == sorted(items)


def test_policy_rejects_leaked_password_with_own_code(hibp):
    password = _strong_password()
    prefix, suffix = _split(password)
    hibp.ranges[prefix] = _range_body({suffix: 1})
    with pytest.raises(HTTPException) as exc:
        ensure_password_acceptable(password)
    assert exc.value.status_code == 400 and exc.value.detail["code"] == "password_leaked"


def test_policy_checks_strength_before_asking_hibp(hibp):
    with pytest.raises(HTTPException) as exc:
        ensure_password_acceptable("kurz")
    assert exc.value.detail["code"] == "password_weak"
    assert hibp.calls == []


def test_admin_account_password_is_checked(hibp, db):
    from app.schemas.admin import PlatformAdminCreate
    from app.services.admin_user_service import PlatformAdminService

    password = _strong_password()
    prefix, suffix = _split(password)
    hibp.ranges[prefix] = _range_body({suffix: 9})
    with pytest.raises(HTTPException) as exc:
        PlatformAdminService().create_admin(
            db, PlatformAdminCreate(email=f"leak-{secrets.token_hex(3)}@example.com", display_name="Leak Test", password=password, role="owner"),
        )
    assert exc.value.detail["code"] == "password_leaked"


# ── Leak-Prüfung beim Login (1.5.2): Präfix-Cache, fällige Prüfung, Abfragegrenze ─────────────


@pytest.fixture
def fetch_counter():
    from app.core.redis_client import get_redis_sync
    from app.core.rate_limit import _legacy_key

    get_redis_sync().delete(_legacy_key(password_leak.FETCH_LIMIT_KEY))
    yield
    get_redis_sync().delete(_legacy_key(password_leak.FETCH_LIMIT_KEY))


def test_login_checks_reuse_the_prefix_cache_and_due_checks_bypass_it(hibp, fetch_counter):
    password = _strong_password()
    prefix, suffix = _split(password)
    hibp.ranges[prefix] = _range_body({suffix: 3})

    assert password_leak.check_password(password).leaked is True
    assert password_leak.check_password(password).leaked is True
    assert len(hibp.calls) == 1  # zweite Anmeldung aus dem Cache (je Präfix, 1 h)
    # Fällige Prüfung (Nachtjob): ohne Cache, Ergebnis wird wieder gecacht
    assert password_leak.check_password(password, fresh=True).leaked is True
    assert len(hibp.calls) == 2
    assert password_leak.check_password(password).leaked is True
    assert len(hibp.calls) == 2


def test_fetch_limit_falls_back_to_the_local_list_instead_of_hammering_hibp(hibp, fetch_counter, monkeypatch):
    monkeypatch.setattr(settings, "password_leak_fetch_per_minute", 1)
    first, second = _strong_password(), _strong_password()
    password_leak.check_password(first)
    assert len(hibp.calls) == 1
    result = password_leak.check_password(second)
    assert len(hibp.calls) == 1  # Grenze erreicht: keine weitere Abfrage
    assert result.source in ("local", "none") and result.leaked is False
