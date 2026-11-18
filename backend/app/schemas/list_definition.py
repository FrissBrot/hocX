from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.entities import Tenant
from app.schemas.base import PublicIdModel

ListValueType = Literal["text", "participant", "participants", "event"]


class ListColumnRead(BaseModel):
    """Eine Spalte einer Liste. ``id`` ist der Spalten-Key in ``ListEntryRead.values`` und in
    Konfigurationen (Gruppieren, Sortieren, Filtern, feste Spalte)."""

    id: str
    title: str
    value_type: ListValueType
    sort_index: int


class ListColumnCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    value_type: ListValueType = "text"


class ListColumnUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    value_type: ListValueType | None = None


class ListColumnOrder(BaseModel):
    column_ids: list[str] = Field(max_length=20)


class ListColumnUsage(BaseModel):
    kind: str
    label: str
    href: str | None = None


class ListDefinitionBase(BaseModel):
    name: str
    description: str | None = None
    is_active: bool = True
    # Quelle der Gruppenstatistik (Einträge = Termin-Tags, die als Gruppe zählen).
    is_group_source: bool = False


class ListDefinitionCreate(ListDefinitionBase):
    # Unbekannte Felder (z. B. alte column_one_value/first_value) ablehnen statt still zu
    # verwerfen - sonst gingen Daten alter Clients unbemerkt verloren (Migration 0186).
    model_config = ConfigDict(extra="forbid")

    # Startspalten; ohne Angabe eine Text-Spalte (Titel aus der UI, z. B. «Name»)
    columns: list[ListColumnCreate] = Field(default_factory=list, max_length=20)


class ListDefinitionUpdate(BaseModel):
    # Unbekannte Felder (z. B. alte column_one_value/first_value) ablehnen statt still zu
    # verwerfen - sonst gingen Daten alter Clients unbemerkt verloren (Migration 0186).
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    description: str | None = None
    is_active: bool | None = None
    is_group_source: bool | None = None
    # Rollen: Spalte, die einen Eintrag benennt / Spalte mit den Verantwortlichen (null = keine)
    label_column_id: str | None = Field(default=None, max_length=64)
    responsible_column_id: str | None = Field(default=None, max_length=64)


class ListDefinitionRead(PublicIdModel, ListDefinitionBase):
    _fk_models: ClassVar[dict[str, type]] = {"tenant_id": Tenant}

    id: uuid.UUID
    tenant_id: uuid.UUID
    content_version: int
    columns: list[ListColumnRead] = Field(default_factory=list)
    label_column_id: str | None = None
    responsible_column_id: str | None = None
    created_at: datetime
    updated_at: datetime

    @field_validator("label_column_id", "responsible_column_id", mode="before")
    @classmethod
    def _role_key_only(cls, value: object) -> object:
        # Aus dem ORM-Objekt kommt die interne Spalten-ID (Zahl); nach aussen geht nur der
        # Spalten-Key, den ListService._definition_read einsetzt - die Zahl nie ausgeben.
        return None if isinstance(value, int) else value


class ListEntryBase(BaseModel):
    sort_index: int = Field(default=0)
    # Spalten-Key -> Wert ({"text_value"}, {"participant_id"}, {"participant_ids"}, {"event_id"})
    values: dict[str, dict[str, Any]] = Field(default_factory=dict)


class ListEntryCreate(ListEntryBase):
    # Unbekannte Felder (z. B. alte column_one_value/first_value) ablehnen statt still zu
    # verwerfen - sonst gingen Daten alter Clients unbemerkt verloren (Migration 0186).
    model_config = ConfigDict(extra="forbid")


class ListEntryUpdate(BaseModel):
    # Unbekannte Felder (z. B. alte column_one_value/first_value) ablehnen statt still zu
    # verwerfen - sonst gingen Daten alter Clients unbemerkt verloren (Migration 0186).
    model_config = ConfigDict(extra="forbid")

    sort_index: int | None = None
    # Nur die genannten Spalten werden geändert; {} leert eine Spalte
    values: dict[str, dict[str, Any]] | None = None


class ListEntryRead(ListEntryBase):
    # Built via explicit keyword construction in ListService._entry_read (values need
    # type-aware id translation - see _denormalize_value), not from_attributes.
    id: uuid.UUID
    list_definition_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
