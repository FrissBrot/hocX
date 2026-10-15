"""Rechte des Document Studio - Erweiterung der bestehenden hocX-Rollen, keine eigene
Berechtigungsarchitektur.

| Fähigkeit              | Rollen                          | Prüfung                 |
|------------------------|---------------------------------|-------------------------|
| Dokumente exportieren  | reader, kassier, writer, admin  | ``require_export``      |
| Vorlagen ansehen       | reader, kassier, writer, admin  | ``require_view``        |
| Vorlagen bearbeiten    | writer, admin                   | ``require_edit``        |
| Vorlagen veröffentlichen, archivieren, zuweisen | admin  | ``require_publish``     |
| Corporate Design (Brand Studio, Assets) verwalten | admin | ``require_brand``     |
| Systemvorlagen verwalten | Plattform-Admin (Adminportal) | admin_security          |

Datenrechte (Mitgliederdaten, Finanzen, Protokoll-Leserecht eingeschränkter Leser) prüfen
Compiler und Bindungen beim Export mit dem exportierenden Benutzer (context.BuildContext).
"""
from __future__ import annotations

from app.core.security import CurrentUser, require_admin, require_reader, require_writer


def require_export(user: CurrentUser) -> CurrentUser:
    return require_reader(user)


def require_view(user: CurrentUser) -> CurrentUser:
    return require_reader(user)


def require_edit(user: CurrentUser) -> CurrentUser:
    return require_writer(user)


def require_publish(user: CurrentUser) -> CurrentUser:
    return require_admin(user)


def require_brand(user: CurrentUser) -> CurrentUser:
    return require_admin(user)


def capabilities(user: CurrentUser) -> dict[str, bool]:
    role = user.current_role
    reader = role in {"reader", "kassier", "writer", "admin"}
    return {
        "export": reader,
        "view_templates": reader,
        "edit_templates": role in {"writer", "admin"},
        "publish_templates": role == "admin",
        "manage_brand": role == "admin",
        "finance_data": "finance" in user.current_tenant_features and reader,
        "personal_data": role in {"writer", "admin"},
    }
