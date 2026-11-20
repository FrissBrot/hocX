"""Session-Register (SEC-AUTH-011, Audit Abschnitt 9.3).

Jede neue Anmeldung legt eine Zeile ``auth_session`` an; ihre ID (``sid``) steht im signierten
Cookie. Damit gibt es:
- Inaktivität (``auth_session_idle_minutes``, Standard 8 h) und absolute Lebensdauer
  (``auth_session_absolute_hours``, Standard 14 Tage),
- Einzel-Widerruf, «Nur dieses Gerät abmelden» vs. «Überall abmelden»,
- die Liste «Angemeldete Geräte» im Profil,
- Frische der letzten starken Anmeldung (``auth_time``/``amr``) für Step-up (SEC-AUTH-010),
- Logout-Kaskade über ``parent_id`` (Session auf einer Mandanten-Domain aus der Domain-Bridge).

``last_seen_at`` wird höchstens alle ``auth_session_touch_seconds`` geschrieben.

Übergang: Cookies ohne ``sid`` (vor dem Update ausgestellt) bleiben bis zu ihrem Ablauf (höchstens
72 h) gültig - niemand muss sich wegen des Updates neu anmelden. Sie erscheinen nicht in der
Geräteliste; «Überall abmelden» beendet sie über ``session_revoke_at``.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import AuthSession


def _now() -> datetime:
    return datetime.now(UTC)


def create(
    db: Session,
    *,
    user_id: int,
    tenant_id: int,
    mfa: bool,
    amr: list[str],
    device_id: int | None = None,
    parent_id: uuid.UUID | None = None,
    host: str | None = None,
    ip_net_hash: str | None = None,
    user_agent_family: str | None = None,
    expires_at: datetime | None = None,
) -> AuthSession:
    """Neue Session (ohne Commit)."""
    now = _now()
    row = AuthSession(
        tenant_id=tenant_id, user_id=user_id, mfa=mfa, amr=sorted(set(amr)), device_id=device_id, parent_id=parent_id,
        host=(host or "")[:255] or None, ip_net_hash=ip_net_hash, user_agent_family=user_agent_family,
        created_at=now, last_seen_at=now, auth_time=now,
        expires_at=expires_at or now + timedelta(hours=settings.auth_session_absolute_hours),
    )
    db.add(row)
    db.flush()
    return row


def validate(db: Session, sid: str | None, user_id: int) -> AuthSession | None:
    """Aktive Session dieses Kontos oder None (unbekannt, widerrufen, abgelaufen, inaktiv).
    Eine wegen Inaktivität abgelaufene Session wird dabei als widerrufen markiert."""
    try:
        session_id = uuid.UUID(str(sid))
    except (TypeError, ValueError):
        return None
    row = db.get(AuthSession, session_id)
    now = _now()
    if row is None or row.user_id != user_id or row.revoked_at is not None or row.expires_at <= now:
        return None
    if row.last_seen_at < now - timedelta(minutes=settings.auth_session_idle_minutes):
        row.revoked_at, row.revoked_reason = now, "idle"
        db.commit()
        return None
    if row.last_seen_at < now - timedelta(seconds=settings.auth_session_touch_seconds):
        row.last_seen_at = now
        db.commit()
    return row


def mark_strong_auth(db: Session, row: AuthSession, method: str) -> None:
    """Step-up bestanden: Frische setzen (ohne Commit)."""
    row.auth_time = _now()
    row.amr = sorted({*row.amr, method})
    if method in ("totp", "passkey"):
        row.mfa = True
    db.flush()


def _with_children(db: Session, ids: list[uuid.UUID]) -> list[uuid.UUID]:
    """IDs inkl. aller Kind-Sessions (Domain-Bridge), höchstens wenige Ebenen tief."""
    found = list(ids)
    frontier = list(ids)
    for _depth in range(5):
        if not frontier:
            break
        frontier = list(db.scalars(select(AuthSession.id).where(AuthSession.parent_id.in_(frontier), AuthSession.revoked_at.is_(None))))
        found += frontier
    return found


def revoke(db: Session, session_ids: list[uuid.UUID], *, reason: str) -> int:
    """Widerruft die Sessions samt Kind-Sessions (ohne Commit)."""
    if not session_ids:
        return 0
    ids = _with_children(db, session_ids)
    return db.execute(
        update(AuthSession).where(AuthSession.id.in_(ids), AuthSession.revoked_at.is_(None)).values(revoked_at=_now(), revoked_reason=reason)
    ).rowcount or 0


def revoke_all(db: Session, user_id: int, *, reason: str, except_id: uuid.UUID | None = None) -> int:
    """Alle Sessions des Kontos ausser ``except_id`` (und dessen Kinder) widerrufen (ohne Commit)."""
    keep = set(_with_children(db, [except_id])) if except_id else set()
    statement = update(AuthSession).where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
    if keep:
        statement = statement.where(AuthSession.id.not_in(keep))
    return db.execute(statement.values(revoked_at=_now(), revoked_reason=reason)).rowcount or 0


def list_active(db: Session, user_id: int) -> list[AuthSession]:
    now = _now()
    return list(db.scalars(
        select(AuthSession)
        .where(
            AuthSession.user_id == user_id,
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > now,
            AuthSession.last_seen_at >= now - timedelta(minutes=settings.auth_session_idle_minutes),
        )
        .order_by(AuthSession.last_seen_at.desc())
    ))


def purge(db: Session, *, keep_days: int = 30) -> int:
    """Abgelaufene/widerrufene Sessions nach ``keep_days`` endgültig löschen (Wartungsjob)."""
    cutoff = _now() - timedelta(days=keep_days)
    deleted = db.execute(
        AuthSession.__table__.delete().where(or_(AuthSession.expires_at < cutoff, AuthSession.revoked_at < cutoff))
    ).rowcount or 0
    db.commit()
    return deleted
