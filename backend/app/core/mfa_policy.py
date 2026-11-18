"""Wann ein Konto einen zweiten Faktor braucht - die EINE Stelle dafür.

Alle Pfade fragen hier nach: jeder Request (``get_optional_current_user``), die Mitschreib-
WebSocket-Verbindung, der Login-Flow (``MfaService.prepare_login``), die Profil-/Admin-Übersicht
(``UserMfaRead.required``) und der Erstlogin über eine Einladung (``mfa.required`` in der Antwort
von ``/api/auth/account-link/complete``, die Seite blendet danach «Später einrichten» aus).

Pflicht, sobald das Konto eine Permission mit ``requires_mfa`` hat (Administration, über Rollen)
ODER sein Mandant MFA für alle Logins verlangt (``tenant.require_mfa``, Migration 0188,
``app.core.tenant_mfa.tenant_requires_mfa``).
"""
from __future__ import annotations

from collections.abc import Iterable

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
    if permissions is None:
        # Spät importiert: app.core.security importiert dieses Modul.
        from app.core.security import load_role_permissions

        permissions, _role_ids = load_role_permissions(db, user_id)
    return requires_mfa(permissions)
