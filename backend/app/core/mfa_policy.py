"""Wann ein Konto einen zweiten Faktor braucht - die EINE Stelle dafür.

Alle Pfade fragen hier nach: jeder Request (``get_optional_current_user``), die Mitschreib-
WebSocket-Verbindung, der Login-Flow (``MfaService.prepare_login``), die Profil-/Admin-Übersicht
(``UserMfaRead.required``) und der Erstlogin über eine Einladung (``mfa.required`` in der Antwort
von ``/api/auth/account-link/complete``, die Seite blendet danach «Später einrichten» aus).

Pflicht, sobald das Konto eine Permission mit ``requires_mfa`` hat (Administration, über Rollen),
eine seiner Rollen MFA verlangt (``tenant_role.require_mfa``, Migration 0192) ODER sein Mandant MFA
für alle Logins verlangt (``tenant.require_mfa``, Migration 0188,
``app.core.tenant_mfa.tenant_requires_mfa``).

Frist (Entscheid 18.11.2026): Wird MFA für ein BESTEHENDES Konto (``first_login_at`` gesetzt) neu
Pflicht, hat es 3 Tage Zeit (``mfa_grace``). Keine Frist bei Pflicht wegen Administrationsrechten
und für neue Konten - die richten den Faktor beim ersten Login ein.
"""
from __future__ import annotations

from collections.abc import Iterable

from datetime import UTC, datetime, timedelta

from sqlalchemy import exists, select, update
from sqlalchemy.orm import Session

from app.core.permissions import requires_mfa


def account_requires_mfa(
    db: Session,
    user_id: int,
    *,
    permissions: Iterable[str] | None = None,
    tenant_id: int | None = None,
) -> bool:
    """True, wenn das Konto ohne bestätigten zweiten Faktor keine Session bekommen darf.

    ``permissions``: schon geladene effektive Permissions (spart die Abfrage auf jedem Request).
    ``tenant_id``: Mandant des Kontos (ohne Angabe aus dem Konto gelesen)."""
    from app.core.tenant_mfa import tenant_requires_mfa
    from app.models import AppUser

    if tenant_id is None:
        user = db.get(AppUser, user_id)
        tenant_id = user.tenant_id if user is not None else None
    if tenant_requires_mfa(db, tenant_id):
        return True
    if _role_requires_mfa(db, user_id):
        return True
    if permissions is None:
        # Spät importiert: app.core.security importiert dieses Modul.
        from app.core.security import load_role_permissions

        permissions, _role_ids = load_role_permissions(db, user_id)
    return requires_mfa(permissions)


MFA_GRACE = timedelta(days=3)


def _role_requires_mfa(db: Session, user_id: int) -> bool:
    from app.models import TenantRole, UserRole

    return bool(db.scalar(select(exists().where(
        UserRole.user_id == user_id, UserRole.role_id == TenantRole.id, TenantRole.require_mfa.is_(True),
    ))))


def _load_permissions(db: Session, user_id: int, permissions: Iterable[str] | None) -> Iterable[str]:
    if permissions is not None:
        return permissions
    from app.core.security import load_role_permissions

    loaded, _role_ids = load_role_permissions(db, user_id)
    return loaded


def mfa_grace_until(
    db: Session,
    user_id: int,
    *,
    permissions: Iterable[str] | None = None,
    tenant_id: int | None = None,
    now: datetime | None = None,
) -> datetime | None:
    """Laufende Frist, in der ein Konto ohne Faktor trotz MFA-Pflicht angemeldet bleiben darf -
    sonst None (keine Pflicht, Pflicht wegen Administrationsrechten, neues Konto oder Frist um).

    Die Frist beginnt beim ersten Erkennen der Pflicht und wird gespeichert (app_user.mfa_grace_until),
    damit sie nicht bei jedem Request neu läuft."""
    from app.models import AppUser

    if not account_requires_mfa(db, user_id, permissions=permissions, tenant_id=tenant_id):
        return None
    if requires_mfa(_load_permissions(db, user_id, permissions)):
        return None  # Administrationsrechte: sofort, ohne Frist
    user = db.get(AppUser, user_id)
    if user is None or user.first_login_at is None:
        return None  # neues Konto: MFA beim ersten Login
    now = now or datetime.now(UTC)
    if user.mfa_grace_until is None:
        deadline = now + MFA_GRACE
        db.execute(update(AppUser).where(AppUser.id == user_id, AppUser.mfa_grace_until.is_(None)).values(mfa_grace_until=deadline))
        db.commit()
        db.refresh(user)
    return user.mfa_grace_until if user.mfa_grace_until and user.mfa_grace_until > now else None
