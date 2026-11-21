"""Bekannte Geräte (SEC-AUTH-006, Audit Abschnitt 6.3/9.3).

Jeder Browser bekommt nach einer erfolgreichen Anmeldung ein signiertes, langlebiges Cookie mit
einer zufälligen Geräte-ID (``hocx_device``, HttpOnly, 90 Tage). Serverseitig steht je Konto der
HMAC dieser ID in ``auth_known_device`` - widerrufbar (Profil › Sicherheit, Passwort-Reset).

Ein bekanntes Gerät ist von der kontoweiten Sperre (L5) und den weichen/harten Quellgrenzen
(L1/L2) ausgenommen, nicht aber von Konto+Quelle (L4) und den Faktor-Grenzen (L6). Damit kann ein
Angreifer, der ein Konto mit Fehlversuchen überzieht, die Inhaberin nicht mehr aussperren.

Das Cookie ist mit ``AUTH_SECRET`` signiert; während einer Rotation gilt auch ``AUTH_SECRET_PREVIOUS``.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import Request, Response
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import AuthKnownDevice

_VERSION = "d1"


def _secrets() -> list[str]:
    return [value for value in (settings.auth_secret, settings.auth_secret_previous) if value]


def _sign(secret: str, device_id: str) -> str:
    key = hmac.new(secret.encode(), b"hocx device cookie v1", hashlib.sha256).digest()
    return base64.urlsafe_b64encode(hmac.new(key, device_id.encode(), hashlib.sha256).digest()[:24]).decode().rstrip("=")


def _hash(secret: str, device_id: str) -> str:
    key = hmac.new(secret.encode(), b"hocx device hash v1", hashlib.sha256).digest()
    return hmac.new(key, device_id.encode(), hashlib.sha256).hexdigest()[:40]


def device_hash(device_id: str) -> str:
    return _hash(settings.auth_secret, device_id)


def _hash_candidates(device_id: str) -> list[str]:
    return [_hash(secret, device_id) for secret in _secrets()]


def cookie_name() -> str:
    name = settings.auth_device_cookie
    if settings.auth_secure_cookies and not name.startswith("__Host-"):
        return f"__Host-{name}"
    return name


def encode_cookie(device_id: str) -> str:
    return f"{_VERSION}.{device_id}.{_sign(settings.auth_secret, device_id)}"


def parse_cookie(value: str | None) -> str | None:
    """Geräte-ID aus einem gültig signierten Cookie, sonst None."""
    if not value or len(value) > 200:
        return None
    parts = value.strip('"').split(".")
    if len(parts) != 3 or parts[0] != _VERSION or not parts[1] or len(parts[1]) > 64:
        return None
    for secret in _secrets():
        if hmac.compare_digest(_sign(secret, parts[1]), parts[2]):
            return parts[1]
    return None


def device_id_from_request(request: Request | None) -> str | None:
    if request is None:
        return None
    # Im Secure-Modus nur das __Host--Cookie (Security-Review M4): ein Cookie ohne Präfix könnte
    # eine Geschwister-Subdomain unterschieben.
    return parse_cookie(request.cookies.get(cookie_name()))


def new_device_id() -> str:
    return secrets.token_urlsafe(18)


def set_cookie(response: Response, device_id: str) -> None:
    response.set_cookie(
        key=cookie_name(),
        value=encode_cookie(device_id),
        httponly=True,
        secure=settings.auth_secure_cookies,
        samesite="lax",
        max_age=settings.auth_device_ttl_days * 24 * 3600,
        path="/",
    )


def _cutoff() -> datetime:
    return datetime.now(UTC) - timedelta(days=settings.auth_device_ttl_days)


def known_device(db: Session, user_id: int, device_id: str | None) -> AuthKnownDevice | None:
    """Bekanntes, nicht widerrufenes, in der Frist genutztes Gerät des Kontos."""
    if not device_id:
        return None
    return db.scalar(
        select(AuthKnownDevice).where(
            AuthKnownDevice.user_id == user_id,
            AuthKnownDevice.device_hash.in_(_hash_candidates(device_id)),
            AuthKnownDevice.revoked_at.is_(None),
            AuthKnownDevice.last_seen_at >= _cutoff(),
        )
    )


def remember(
    db: Session, *, user_id: int, tenant_id: int, device_id: str, user_agent_family: str | None, country: str | None = None,
) -> tuple[AuthKnownDevice, bool]:
    """Gerät als bekannt speichern bzw. auffrischen (ohne Commit). Liefert (Gerät, neu?)."""
    existing = db.scalar(
        select(AuthKnownDevice).where(AuthKnownDevice.user_id == user_id, AuthKnownDevice.device_hash.in_(_hash_candidates(device_id)))
    )
    now = datetime.now(UTC)
    if existing is not None:
        was_usable = existing.revoked_at is None and existing.last_seen_at >= _cutoff()
        existing.last_seen_at = now
        existing.revoked_at = None
        existing.device_hash = device_hash(device_id)
        if user_agent_family:
            existing.user_agent_family = user_agent_family
        if country:
            existing.last_country = country
        db.flush()
        return existing, not was_usable
    row = AuthKnownDevice(tenant_id=tenant_id, user_id=user_id, device_hash=device_hash(device_id), user_agent_family=user_agent_family, last_country=country, last_seen_at=now, created_at=now)
    db.add(row)
    db.flush()
    return row, True


def revoke_all(db: Session, user_id: int) -> int:
    """Alle Geräte des Kontos vergessen (ohne Commit), z. B. nach «Passwort vergessen»."""
    return db.execute(
        update(AuthKnownDevice).where(AuthKnownDevice.user_id == user_id, AuthKnownDevice.revoked_at.is_(None)).values(revoked_at=datetime.now(UTC))
    ).rowcount or 0


def list_active(db: Session, user_id: int) -> list[AuthKnownDevice]:
    return list(db.scalars(
        select(AuthKnownDevice)
        .where(AuthKnownDevice.user_id == user_id, AuthKnownDevice.revoked_at.is_(None), AuthKnownDevice.last_seen_at >= _cutoff())
        .order_by(AuthKnownDevice.last_seen_at.desc())
    ))


def revoke_others(db: Session, user_id: int, keep_device_id: str | None) -> int:
    """Alle bekannten Geräte ausser dem aktuellen vergessen (ohne Commit), z. B. beim Passwortwechsel."""
    statement = update(AuthKnownDevice).where(AuthKnownDevice.user_id == user_id, AuthKnownDevice.revoked_at.is_(None))
    if keep_device_id:
        statement = statement.where(AuthKnownDevice.device_hash.not_in(_hash_candidates(keep_device_id)))
    return db.execute(statement.values(revoked_at=datetime.now(UTC))).rowcount or 0
