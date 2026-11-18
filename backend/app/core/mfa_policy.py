"""Wann ein Konto einen zweiten Faktor braucht - die EINE Stelle dafür.

Alle Pfade fragen hier nach: jeder Request (``get_optional_current_user``), die Mitschreib-
WebSocket-Verbindung, der Login-Flow (``MfaService.prepare_login``), die Profil-/Admin-Übersicht
(``UserMfaRead.required``) und der Erstlogin über eine Einladung (``mfa.required`` in der Antwort
von ``/api/auth/account-link/complete``, die Seite blendet danach «Später einrichten» aus).

Heute: Pflicht, sobald das Konto eine Permission mit ``requires_mfa`` hat (Administration, über
Rollen). Eine Mandanten-Einstellung «MFA für alle Logins» wird nur hier ergänzt - der
``tenant_id``-Parameter ist dafür schon da, damit kein Aufrufer angepasst werden muss.
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
    ``tenant_id``: Mandant des Kontos, für eine künftige Mandanten-Pflicht (heute ungenutzt)."""
    _ = tenant_id
    if permissions is None:
        # Spät importiert: app.core.security importiert dieses Modul.
        from app.core.security import load_role_permissions

        permissions, _role_ids = load_role_permissions(db, user_id)
    return requires_mfa(permissions)
