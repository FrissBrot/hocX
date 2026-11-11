"""Konto und Sicherheit (Benachrichtigungen Phase 3, docs/NOTIFICATIONS.md).

Einmal-Links («Passwort vergessen», Einladung):
- Anfrage bzw. Einladung legt eine Zeile `account_token` ohne Token an und veröffentlicht eine
  Benachrichtigung. Offene ältere Links derselben Art werden dabei widerrufen.
- Erst beim Versand (dispatch -> ``items_for``) entsteht das Token: zufällig, nur der SHA-256-Hash
  wird gespeichert, das Token selbst steht nur im URL-Fragment des Links in der Mail
  (``/auth/set-password#token=…``, SECURITY-RULES 3.2). Gültig ab Versand: Passwort 60 Minuten,
  Einladung 7 Tage. Einlösen ist einmalig.
- «Passwort vergessen» antwortet immer gleich, ob es das Konto gibt oder nicht (kein Orakel).
- Setzen des Passworts beendet alle Sitzungen (session_revoke_at). Ein eingerichteter zweiter
  Faktor bleibt bestehen und wird beim nächsten Login weiter verlangt.

Sicherheitshinweise (Passwort geändert, zweiter Faktor geändert/zurückgesetzt) gehen immer raus,
die Person kann sie nicht abschalten (Kategorie `account`, nicht wählbar).
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models import AccountToken, AppUser, Tenant
from app.notifications import publish
from app.services.audit_service import AuditService

PURPOSES = ("password_reset", "invite")
TOKEN_TTL = {"password_reset": timedelta(minutes=60), "invite": timedelta(days=7)}
KIND_BY_PURPOSE = {"password_reset": "account.password_reset", "invite": "account.invite"}
SET_PASSWORD_PATH = "/auth/set-password"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _revoke_open(db: Session, user_id: int, purpose: str) -> None:
    db.execute(
        update(AccountToken)
        .where(AccountToken.user_id == user_id, AccountToken.purpose == purpose, AccountToken.used_at.is_(None), AccountToken.revoked_at.is_(None))
        .values(revoked_at=_now())
    )


def _issue(db: Session, user: AppUser, purpose: str, *, created_by_user_id: int | None) -> AccountToken:
    """Neuer Link (noch ohne Token) plus Benachrichtigung, ohne Commit."""
    _revoke_open(db, user.id, purpose)
    token = AccountToken(tenant_id=user.tenant_id, user_id=user.id, purpose=purpose, created_by_user_id=created_by_user_id)
    db.add(token)
    db.flush()
    publish(db, kind=KIND_BY_PURPOSE[purpose], tenant_id=user.tenant_id, recipient_ids=[user.id], subject_id=token.id)
    return token


# ── Passwort vergessen ──────────────────────────────────────────────────


def request_password_reset(db: Session, email: str) -> None:
    """Legt für ein aktives Konto mit Login einen Link an. Ohne passendes Konto passiert nichts;
    der Aufrufer antwortet in beiden Fällen gleich."""
    normalized = (email or "").strip().lower()
    if not normalized:
        return
    user = db.scalar(select(AppUser).where(AppUser.email == normalized, AppUser.login_enabled.is_(True)))
    if user is None or not user.is_active:
        return
    _issue(db, user, "password_reset", created_by_user_id=None)
    db.commit()
    AuditService().log(db, action="user.password_reset_requested", tenant_id=user.tenant_id, actor_user_id=user.id, entity_type="app_user", entity_id=user.id)


# ── Einladung ───────────────────────────────────────────────────────────


def open_invite(db: Session, user_id: int) -> AccountToken | None:
    return db.scalar(
        select(AccountToken)
        .where(AccountToken.user_id == user_id, AccountToken.purpose == "invite", AccountToken.used_at.is_(None), AccountToken.revoked_at.is_(None))
        .order_by(AccountToken.id.desc())
        .limit(1)
    )


def invite(db: Session, user: AppUser, *, actor_user_id: int) -> AccountToken:
    """Einladung an ein Konto ohne Login (Prüfungen von Recht, E-Mail und Limit im Aufrufer)."""
    token = _issue(db, user, "invite", created_by_user_id=actor_user_id)
    db.commit()
    return token


def revoke_all_links(db: Session, user_id: int) -> None:
    """Ohne Commit: E-Mail, Passwort, Login oder Aktiv-Status haben sich geändert - ein Link an
    die alte Adresse bzw. für den alten Zustand darf danach nicht mehr funktionieren."""
    for purpose in PURPOSES:
        _revoke_open(db, user_id, purpose)


def revoke_invite(db: Session, user_id: int) -> None:
    _revoke_open(db, user_id, "invite")
    db.commit()


# ── Einlösen ────────────────────────────────────────────────────────────


def _valid_token(db: Session, token: str) -> tuple[AccountToken, AppUser] | None:
    if not token or len(token) > 200:
        return None
    row = db.scalar(select(AccountToken).where(AccountToken.token_hash == hash_token(token)))
    if row is None or row.used_at is not None or row.revoked_at is not None or row.expires_at is None or row.expires_at <= _now():
        return None
    user = db.get(AppUser, row.user_id)
    if user is None or user.tenant_id != row.tenant_id or not user.is_active or not (user.email or "").strip():
        return None
    # Passwort zurücksetzen nur mit Login, Einladung nur ohne (danach hat das Konto einen Login)
    if (row.purpose == "password_reset") != bool(user.login_enabled):
        return None
    return row, user


def preview(db: Session, token: str) -> dict | None:
    found = _valid_token(db, token)
    if found is None:
        return None
    row, user = found
    tenant_name = db.scalar(select(Tenant.name).where(Tenant.id == user.tenant_id)) or ""
    return {"purpose": row.purpose, "display_name": user.display_name, "email": user.email, "tenant_name": tenant_name}


def complete(db: Session, token: str, password: str) -> str:
    """Setzt das Passwort (Einladung: dazu den Login) und verbraucht den Link. Liefert den Zweck."""
    from app.services import user_limit_service
    from app.services.user_service import UserService

    found = _valid_token(db, token)
    if found is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Der Link ist ungültig oder abgelaufen.")
    row, user = found
    # Gegen gleichzeitiges zweites Einlösen: Zeile sperren und erneut prüfen
    locked = db.scalar(select(AccountToken).where(AccountToken.id == row.id).with_for_update())
    if locked is None or locked.used_at is not None or locked.revoked_at is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Der Link ist ungültig oder abgelaufen.")
    now = _now()
    if row.purpose == "invite":
        UserService().ensure_login_email_available(db, user.email, excluding_user_id=user.id)
        user_limit_service.ensure_login_capacity(db, user.tenant_id)
        user.email = user.email.strip().lower()
        user.login_enabled = True
    user.password_hash = hash_password(password)
    user.session_revoke_at = now
    locked.used_at = now
    _revoke_open(db, user.id, "password_reset")
    _revoke_open(db, user.id, "invite")
    if row.purpose == "password_reset":
        notify_security(db, user, "security.password_changed")
    db.commit()
    AuditService().log(
        db, action="user.password_reset" if row.purpose == "password_reset" else "user.invite_accepted",
        tenant_id=user.tenant_id, actor_user_id=user.id, entity_type="app_user", entity_id=user.id,
    )
    return row.purpose


# ── Sicherheitshinweise ─────────────────────────────────────────────────


def notify_security(db: Session, user: AppUser | None, kind: str, *, by_admin: bool = False) -> None:
    """Sicherheitshinweis an die Person selbst (ohne Commit, in der Transaktion des Aufrufers)."""
    if user is None or not user.login_enabled:
        return
    publish(db, kind=kind, tenant_id=user.tenant_id, recipient_ids=[user.id], payload={"at": _now().isoformat(), "by_admin": by_admin})


# ── Versand (dispatch.ITEM_LOADERS) ─────────────────────────────────────


def link_items_for(db: Session, notifications: list, recipient_id: int, *, base_url: str | None = None) -> dict[int, dict]:
    """Erzeugt beim Versand das Token des neuesten offenen Links; alles andere ist überholt."""
    if not base_url:
        return {}
    items: dict[int, dict] = {}
    for notification in sorted(notifications, key=lambda n: n.id, reverse=True)[:1]:
        row = db.get(AccountToken, notification.subject_id) if notification.subject_id else None
        if row is None or row.user_id != recipient_id or row.tenant_id != notification.tenant_id or row.used_at or row.revoked_at:
            continue
        user = db.get(AppUser, recipient_id)
        if user is None or (row.purpose == "password_reset") != bool(user.login_enabled):
            continue
        token = secrets.token_urlsafe(32)
        now = _now()
        row.token_hash, row.sent_at, row.expires_at = hash_token(token), now, now + TOKEN_TTL[row.purpose]
        items[notification.id] = {
            "kind": notification.kind,
            "link": f"{base_url}{SET_PASSWORD_PATH}#token={token}",
            "valid_hours": int(TOKEN_TTL[row.purpose].total_seconds() // 3600),
            "valid_minutes": int(TOKEN_TTL[row.purpose].total_seconds() // 60),
        }
    return items


def security_items_for(db: Session, notifications: list, recipient_id: int, **_) -> dict[int, dict]:
    items: dict[int, dict] = {}
    for notification in notifications:
        at = notification.payload.get("at")
        items[notification.id] = {
            "kind": notification.kind,
            "at": datetime.fromisoformat(at) if at else notification.created_at,
            "by_admin": bool(notification.payload.get("by_admin")),
        }
    return items
