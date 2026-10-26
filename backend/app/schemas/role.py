from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


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
    user_count: int
    # Standardrolle admin: nicht änderbar, nicht löschbar.
    locked: bool = False


class RoleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=500)
    permissions: list[str] = Field(default_factory=list, max_length=100)


class RoleUpdate(BaseModel):
    # Bei Standardrollen setzt ein leerer Name auf die übersetzte Standardbezeichnung zurück.
    name: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=500)
    permissions: list[str] | None = Field(default=None, max_length=100)


class UserRolesUpdate(BaseModel):
    role_ids: list[uuid.UUID] = Field(max_length=50)


class PermissionInfo(BaseModel):
    key: str
    area: str
    feature: str | None = None
    requires_mfa: bool = False
    implies: list[str] = Field(default_factory=list)
