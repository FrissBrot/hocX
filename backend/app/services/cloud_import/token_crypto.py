"""Verschlüsselung der OAuth-Tokens der Cloud-Verbindungen (import_connection, Plan §5.5, E-6).

Eigener Schlüssel ``CLOUD_IMPORT_TOKEN_KEY`` (nicht ADMIN_AUTH_SECRET: eigene Zuständigkeit, eigene
Rotation). MultiFernet: verschlüsselt wird immer mit dem aktuellen Schlüssel, entschlüsselt auch mit
``CLOUD_IMPORT_TOKEN_KEY_PREVIOUS`` (Rotation: neuen Schlüssel setzen, alten als _PREVIOUS, nach
spätestens 7 Tagen - länger lebt keine Verbindung ohne Nutzung - _PREVIOUS leeren).

Ohne Schlüssel gibt es keine API-Quellen (``is_configured`` false → kein Anbieter wird angeboten).
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.core.config import settings


class TokenKeyMissing(RuntimeError):
    """CLOUD_IMPORT_TOKEN_KEY fehlt - API-Quellen sind abgeschaltet."""


class TokenDecryptError(RuntimeError):
    """Token mit keinem bekannten Schlüssel lesbar (Schlüssel verloren/rotiert): neu anmelden."""


def _derive(secret: str) -> Fernet:
    # env_migrate.sh erzeugt 64 Hex-Zeichen; Fernet braucht 32 Byte urlsafe-base64. Ableitung per
    # SHA-256 mit Kontext, damit derselbe Wert nie als Schlüssel einer anderen Funktion taugt.
    digest = hashlib.sha256(b"hocx-cloud-import-token-v1:" + secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def is_configured() -> bool:
    return bool(settings.cloud_import_token_key)


def _multi() -> MultiFernet:
    if not settings.cloud_import_token_key:
        raise TokenKeyMissing("CLOUD_IMPORT_TOKEN_KEY fehlt")
    keys = [_derive(settings.cloud_import_token_key)]
    if settings.cloud_import_token_key_previous:
        keys.append(_derive(settings.cloud_import_token_key_previous))
    return MultiFernet(keys)


def encrypt(plain: str | None) -> str | None:
    if not plain:
        return None
    return _multi().encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return _multi().decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        # Bewusst ohne den Wert in der Meldung
        raise TokenDecryptError("Token nicht entschlüsselbar") from exc


def rotate(value: str | None) -> str | None:
    """Mit dem aktuellen Schlüssel neu verschlüsseln (nach einer Rotation beim nächsten Gebrauch)."""
    if not value:
        return None
    try:
        return _multi().rotate(value.encode("ascii")).decode("ascii")
    except (InvalidToken, ValueError) as exc:
        raise TokenDecryptError("Token nicht entschlüsselbar") from exc
