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
    SCOPED_PERMISSIONS,
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
    "SCOPED_PERMISSIONS",
    "SCOPE_ALL",
    "SCOPE_ASSIGNED",
    "P",
    "PermissionDef",
    "DEFAULT_ROLE_KEY",
    "assigned_only_permissions",
    "effective_permissions",
    "expand",
    "resolve_scopes",
    "requires_mfa",
]

# Standardrolle, die immer alle Permissions hat (nicht änderbar, nicht löschbar) und die
# Standardrolle für neue Konten/Teilnehmende (wie bisher reader).
ADMIN_ROLE_KEY = "admin"
DEFAULT_ROLE_KEY = "reader"

_KNOWN = frozenset(P)

# Reichweiten (Plan «Berechtigungen», Phase 4). In tenant_role_permission.scope steht NULL für alle.
SCOPE_ALL = "all"
SCOPE_ASSIGNED = "assigned"


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


def resolve_scopes(role_permission_keys: Iterable[str], scopes: dict[str, str | None]) -> dict[P, str]:
    """Reichweite je Recht mit Reichweite (SCOPED_PERMISSIONS) innerhalb **einer** Rolle.

    ``scopes`` sind die ausdrücklich gesetzten Reichweiten (Rollen-Editor bzw. gespeicherte Zeilen).
    Implikationen erben die Reichweite: Ein Recht gilt für alle, wenn es selbst «alle» hat oder ein
    Recht der Rolle es impliziert, das für alle gilt - ein Recht ohne Reichweite (z. B.
    submissions.manage) gilt immer für alle. Ohne eigene Angabe übernimmt ein impliziertes Recht die
    Reichweite der implizierenden (review(assigned) => read(assigned)); ein Recht, das weder gesetzt
    noch impliziert ist, gilt für alle (Standard, bisheriges Verhalten)."""
    keys = expand(role_permission_keys)
    explicit = {P(key): value for key, value in scopes.items() if key in _KNOWN}
    resolved: dict[P, str] = {}

    def scope_of(key: P) -> str:
        if key in resolved:
            return resolved[key]
        values: list[str] = []
        if key in explicit and explicit[key] is not None:
            values.append(explicit[key] or SCOPE_ALL)
        for source in keys:
            if source != key and key in CATALOG[source].implies:
                values.append(scope_of(source) if source in SCOPED_PERMISSIONS else SCOPE_ALL)
        resolved[key] = SCOPE_ASSIGNED if values and SCOPE_ALL not in values else SCOPE_ALL
        return resolved[key]

    return {key: scope_of(key) for key in keys if key in SCOPED_PERMISSIONS}


def assigned_only_permissions(roles: Iterable[tuple[str | None, Iterable[tuple[str, str | None]]]]) -> frozenset[P]:
    """Rechte mit Reichweite, die ein Konto über keine seiner Rollen für alle hat.

    ``roles``: je Rolle (system_key, [(permission_key, gespeicherte Reichweite), …]). Gespeichert ist
    die aufgelöste Menge (role_service), NULL bedeutet dort «alle». Die Standardrolle admin hat
    immer alles für alle."""
    granted_all: set[P] = set()
    granted: set[P] = set()
    for system_key, rows in roles:
        if system_key == ADMIN_ROLE_KEY:
            return frozenset()
        rows = list(rows)
        scopes = resolve_scopes((key for key, _ in rows), {key: (scope or SCOPE_ALL) for key, scope in rows})
        granted.update(scopes)
        granted_all.update(key for key, scope in scopes.items() if scope == SCOPE_ALL)
    return frozenset(granted - granted_all)
