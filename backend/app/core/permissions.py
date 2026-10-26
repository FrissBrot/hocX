"""Berechtigungen (RBAC) - Hilfsfunktionen zum generierten Katalog.

Der Katalog selbst (Keys, Bereiche, Feature-Bindung, MFA-Pflicht, Implikationen, Standardrollen)
kommt ausschliesslich aus permissions/catalog.json (generiert nach permissions_generated.py,
siehe scripts/sync-permission-catalog.py). Architektur und Entscheidungen:
docs/RBAC_ARCHITECTURE_PROPOSAL.md.

- Funktionsberechtigung: ``CurrentUser.can(P.X)`` / ``security.require_permission(user, P.X)``.
- Ressourcenberechtigung (dieser Datensatz?): weiterhin gezielt in services/access_service.py
  (Mandant, Protokollstatus, Teilnehmer-Zuordnung, eigene Daten) - kein Policy-System.
"""
from __future__ import annotations

from collections.abc import Iterable

from app.core.permissions_generated import (
    AREAS,
    CATALOG,
    SYSTEM_ROLE_KEYS,
    SYSTEM_ROLE_PERMISSIONS,
    P,
    PermissionDef,
)

__all__ = [
    "AREAS",
    "ADMIN_ROLE_KEY",
    "CATALOG",
    "SYSTEM_ROLE_KEYS",
    "SYSTEM_ROLE_PERMISSIONS",
    "P",
    "PermissionDef",
    "DEFAULT_ROLE_KEY",
    "effective_permissions",
    "expand",
    "requires_mfa",
]

# Standardrolle, die immer alle Permissions hat (nicht änderbar, nicht löschbar) und die
# Standardrolle für neue Konten/Teilnehmende (wie bisher reader).
ADMIN_ROLE_KEY = "admin"
DEFAULT_ROLE_KEY = "reader"

_KNOWN = frozenset(P)


def expand(keys: Iterable[str]) -> frozenset[P]:
    """Ergänzt die festen Implikationen des Katalogs (z. B. meetings.edit => meetings.read_drafts
    => meetings.read). Unbekannte Keys (Altlasten in der DB) werden verworfen - default deny."""
    pending = [P(key) for key in keys if key in _KNOWN]
    result: set[P] = set()
    while pending:
        key = pending.pop()
        if key in result:
            continue
        result.add(key)
        pending.extend(CATALOG[key].implies)
    return frozenset(result)


def effective_permissions(role_permission_keys: Iterable[str], system_keys: Iterable[str | None]) -> frozenset[P]:
    """Vereinigungsmenge aller Rollen eines Kontos. Die Standardrolle admin bedeutet immer alle
    Permissions - auch solche, die nach dem Anlegen der Rolle neu in den Katalog kamen."""
    if ADMIN_ROLE_KEY in set(system_keys):
        return frozenset(P)
    return expand(role_permission_keys)


def requires_mfa(permissions: Iterable[str]) -> bool:
    """MFA ist Pflicht, sobald ein Konto eine Permission mit requires_mfa hat (Administration).
    Mit den Standardrollen ist das genau die bisherige Regel (nur admin)."""
    return any(key in _KNOWN and CATALOG[P(key)].requires_mfa for key in permissions)
