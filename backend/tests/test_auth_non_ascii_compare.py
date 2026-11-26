"""Nicht-ASCII-Text in hmac.compare_digest (Nachtlauf 2026-11-26, auth-session/eingaben).

``hmac.compare_digest`` mit zwei str wirft TypeError, sobald einer Nicht-ASCII-Zeichen enthält.
- Gerätecookie: die Signatur stammt aus dem Cookie-Header (latin-1); jeder Login und jede
  Passwort-Reset-Anfrage wertet ihn aus → 500 ohne Anmeldung.
- TOTP: ``str.isdigit()`` lässt Unicode-Ziffern («١٢٣٤٥٦», «²») durch → 500 statt «Code ungültig».
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.auth_security import devices
from app.core import rate_limit
from app.core.db import get_db
from app.core.redis_client import get_redis_sync
from app.core.totp import TOTP_STEP_SECONDS, _hotp, generate_totp_secret, verify_totp_code
from app.main import app

ARABIC_INDIC = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")


def _flush() -> None:
    client = get_redis_sync()
    for pattern in ("ratelimit:*", "authsec:*", "authblock:*"):
        for key in client.scan_iter(pattern):
            client.delete(key)
    rate_limit.local_window.clear()


@pytest.fixture(autouse=True)
def _clean():
    _flush()
    yield
    _flush()


@pytest.mark.parametrize("signature", ["é" * 32, "abc€", "ÿ"])
def test_device_cookie_with_non_ascii_signature_is_invalid(signature):
    assert devices.parse_cookie(f"d1.someid.{signature}") is None


def test_valid_device_cookie_still_parses():
    assert devices.parse_cookie(devices.encode_cookie("dev123")) == "dev123"


@pytest.mark.parametrize("path, body", [
    ("/api/auth/login", {"email": "nobody@example.com", "password": "wrong"}),
    ("/api/auth/password-reset/request", {"email": "nobody@example.com"}),
])
def test_non_ascii_device_cookie_on_public_routes_is_no_500(db, path, body):
    app.dependency_overrides[get_db] = lambda: db
    try:
        client = TestClient(app, base_url="https://hocx.example", raise_server_exceptions=False)
        cookie = f"{devices.cookie_name()}=d1.someid.abc\xe9".encode("latin-1")
        res = client.post(path, json=body, headers=[(b"cookie", cookie)])
    finally:
        app.dependency_overrides.pop(get_db, None)
    assert res.status_code < 500, res.text


@pytest.mark.parametrize("code", ["١٢٣٤٥٦", "12345²", "١٢ ٣٤ ٥٦"])
def test_totp_with_unicode_digits_does_not_raise(code):
    assert verify_totp_code(generate_totp_secret(), code) is None


def test_totp_in_other_numeral_system_is_accepted():
    secret = generate_totp_secret()
    now = datetime.now(UTC)
    counter = int(now.timestamp() // TOTP_STEP_SECONDS)
    code = _hotp(secret, counter).translate(ARABIC_INDIC)
    assert verify_totp_code(secret, code, now=now, window=0) == counter


def test_superscript_is_not_a_digit():
    secret = generate_totp_secret()
    now = datetime.now(UTC)
    counter = int(now.timestamp() // TOTP_STEP_SECONDS)
    code = _hotp(secret, counter)
    assert verify_totp_code(secret, code[:5] + "²", now=now, window=0) is None
