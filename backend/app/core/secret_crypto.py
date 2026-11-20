"""Symmetric encryption for small secret values stored at rest in the DB (e.g. TOTP secrets of
tenant users - originally introduced for the admin SSO client secret, security audit 2026-08-13,
finding M3; the admin SSO was removed in 0205). Reuses ADMIN_AUTH_SECRET rather than introducing a
second app secret to manage: that value is already required to be a random 32+ char string in
production (see Settings.validate_for_production)."""
from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


def _fernet() -> Fernet:
    # Fernet requires a 32-byte urlsafe-base64 key; derive one deterministically from the
    # existing admin secret so there's nothing new to provision or rotate separately.
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.admin_auth_secret.encode()).digest())
    return Fernet(key)


def encrypt_secret(plain: str) -> str:
    if not plain:
        return plain
    return _fernet().encrypt(plain.encode()).decode()


def decrypt_secret(value: str) -> str:
    """Decrypts a value previously written by encrypt_secret. Falls back to returning the
    input unchanged if it isn't a valid Fernet token - this keeps old plaintext rows (from
    before this encryption was introduced, in an environment where the migration hasn't run
    yet) working rather than hard-failing the SSO login flow."""
    if not value:
        return value
    try:
        return _fernet().decrypt(value.encode()).decode()
    except (InvalidToken, ValueError):
        return value
