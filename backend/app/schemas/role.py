from __future__ import annotations

import uuid

from typing import Literal

from pydantic import BaseModel, Field

# Reichweite eines Rechts mit Reichweite (permissions/catalog.json "scopes", Migration 0195)
Scope = Literal["all", "assigned"]


class RoleRef(BaseModel):
    """Kurzform einer Rolle an Konten (Benutzerliste, Session). name ist NULL für unbenannte
    Standardrollen - die Oberfläche übersetzt dann system_key."""

    id: uuid.UUID
    name: str | None = None
    system_key: str | None = None


class RoleRead(RoleRef):
    description: str | None = None
    # Effektive Berechtigungen inkl. Implikationen; Standardrolle admin: alle.
    permissions: list[str]
    # Reichweite je Recht mit Reichweite, das die Rolle hat (aufgelöst inkl. Implikationen)
    scopes: dict[str, Scope] = Field(default_factory=dict)
    user_count: int
    # Standardrolle admin: nicht änderbar, nicht löschbar.
    locked: bool = False
    # MFA für alle Konten mit dieser Rolle (Migration 0192)
    require_mfa: bool = False


class RoleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=500)
    permissions: list[str] = Field(default_factory=list, max_length=100)
    # Reichweiten für Rechte mit Reichweite; fehlt ein Recht, erbt es von implizierenden Rechten
    # bzw. gilt für alle (role_service._validated_scopes)
    scopes: dict[str, Scope] | None = Field(default=None, max_length=20)
    require_mfa: bool = False


class RoleUpdate(BaseModel):
    # Bei Standardrollen setzt ein leerer Name auf die übersetzte Standardbezeichnung zurück.
    name: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=500)
    permissions: list[str] | None = Field(default=None, max_length=100)
    # None = Reichweiten unverändert lassen (auch wenn permissions neu gesetzt wird)
    scopes: dict[str, Scope] | None = Field(default=None, max_length=20)
    require_mfa: bool | None = None


class UserRolesUpdate(BaseModel):
    role_ids: list[uuid.UUID] = Field(max_length=50)


class PermissionInfo(BaseModel):
    key: str
    area: str
    feature: str | None = None
    requires_mfa: bool = False
    implies: list[str] = Field(default_factory=list)
    scopes: list[str] = Field(default_factory=list)
