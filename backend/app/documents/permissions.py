"""Rechte des Document Studio - abgebildet auf die zentralen Berechtigungen (RBAC,
core/permissions.py), keine eigene Berechtigungsarchitektur.

| Fähigkeit              | Berechtigung            | Prüfung                 |
|------------------------|-------------------------|-------------------------|
| Dokumente exportieren  | meetings.read           | ``require_export``      |
| Vorlagen ansehen       | meetings.read           | ``require_view``        |
| Vorlagen bearbeiten    | templates.edit          | ``require_edit``        |
| Vorlagen veröffentlichen, archivieren, zuweisen | settings.manage | ``require_publish`` |
| Corporate Design (Brand Studio, Assets) verwalten | settings.manage | ``require_brand`` |
| Systemvorlagen verwalten | Plattform-Admin (Adminportal) | admin_security    |

Datenrechte (Mitgliederdaten, Finanzen, Protokoll-Leserecht eingeschränkter Leser) prüfen
Compiler und Bindungen beim Export mit dem exportierenden Benutzer (context.BuildContext).
"""
from __future__ import annotations

from app.core.permissions import P
from app.core.security import CurrentUser, require_permission


def require_export(user: CurrentUser) -> CurrentUser:
    return require_permission(user, P.MEETINGS_READ)


def require_view(user: CurrentUser) -> CurrentUser:
    return require_permission(user, P.MEETINGS_READ)


def require_edit(user: CurrentUser) -> CurrentUser:
    return require_permission(user, P.TEMPLATES_EDIT)


def require_publish(user: CurrentUser) -> CurrentUser:
    return require_permission(user, P.SETTINGS_MANAGE)


def require_brand(user: CurrentUser) -> CurrentUser:
    return require_permission(user, P.SETTINGS_MANAGE)


def sees_personal_data(user: CurrentUser) -> bool:
    """Personendaten (Mitgliederlisten, Anwesenheitslisten, Ein-/Austritte, Listen) in Dokumenten:
    Teilnehmerpflege oder Protokollführung - bisher Rolle writer/admin (Katalog-Zugriff "writer")."""
    return user.can(P.PARTICIPANTS_MANAGE) or user.can(P.MEETINGS_EDIT)


def capabilities(user: CurrentUser) -> dict[str, bool]:
    reads = user.can(P.MEETINGS_READ)
    return {
        "export": reads,
        "view_templates": reads,
        "edit_templates": user.can(P.TEMPLATES_EDIT),
        "publish_templates": user.can(P.SETTINGS_MANAGE),
        "manage_brand": user.can(P.SETTINGS_MANAGE),
        "finance_data": user.can(P.FINANCES_READ),
        "personal_data": sees_personal_data(user),
        # Protokollentwürfe ohne Wasserzeichen exportieren (STUDIO-007)
        "unmark_drafts": user.can(P.MEETINGS_EDIT),
    }
