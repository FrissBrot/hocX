from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import UTC, datetime
from urllib.parse import quote


TOTP_STEP_SECONDS = 30
TOTP_DIGITS = 6


def generate_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def normalize_totp_code(code: str) -> str:
    return "".join(ch for ch in code if ch.isdigit())


def build_totp_uri(*, issuer: str, account_name: str, secret: str) -> str:
    label = quote(f"{issuer}:{account_name}")
    issuer_param = quote(issuer)
    return f"otpauth://totp/{label}?secret={secret}&issuer={issuer_param}&algorithm=SHA1&digits={TOTP_DIGITS}&period={TOTP_STEP_SECONDS}"


def _decode_secret(secret: str) -> bytes:
    padding = "=" * (-len(secret) % 8)
    return base64.b32decode((secret + padding).upper(), casefold=True)


def _hotp(secret: str, counter: int) -> str:
    digest = hmac.new(_decode_secret(secret), counter.to_bytes(8, "big"), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code_int = int.from_bytes(digest[offset : offset + 4], "big") & 0x7FFF_FFFF
    return str(code_int % (10 ** TOTP_DIGITS)).zfill(TOTP_DIGITS)


def current_totp_code(secret: str, *, now: datetime | None = None) -> str:
    current = int((now or datetime.now(UTC)).timestamp() // TOTP_STEP_SECONDS)
    return _hotp(secret, current)


def verify_totp_code(
    secret: str,
    code: str,
    *,
    now: datetime | None = None,
    window: int = 1,
    min_counter: int | None = None,
) -> int | None:
    normalized = normalize_totp_code(code)
    if len(normalized) != TOTP_DIGITS:
        return None

    current = int((now or datetime.now(UTC)).timestamp() // TOTP_STEP_SECONDS)
    for offset in range(-window, window + 1):
        counter = current + offset
        if min_counter is not None and counter <= min_counter:
            continue
        if hmac.compare_digest(_hotp(secret, counter), normalized):
            return counter
    return None
