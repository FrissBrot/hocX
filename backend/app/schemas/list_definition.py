from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field

from app.models.entities import Tenant
from app.schemas.base import PublicIdModel

ListValueType = Literal["text", "participant", "participants", "event"]


class ListDefinitionBase(BaseModel):
    name: str
    description: str | None = None
    column_one_title: str
    column_one_value_type: ListValueType
    column_two_title: str
    column_two_value_type: ListValueType
    is_active: bool = True


class ListDefinitionCreate(ListDefinitionBase):
    pass


class ListDefinitionUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    column_one_title: str | None = None
    column_one_value_type: ListValueType | None = None
    column_two_title: str | None = None
    column_two_value_type: ListValueType | None = None
    is_active: bool | None = None


class ListDefinitionRead(PublicIdModel, ListDefinitionBase):
    _fk_models: ClassVar[dict[str, type]] = {"tenant_id": Tenant}

    id: uuid.UUID
    tenant_id: uuid.UUID
    content_version: int
    created_at: datetime
    updated_at: datetime


class ListEntryBase(BaseModel):
    sort_index: int = Field(default=0)
    column_one_value: dict[str, Any] = Field(default_factory=dict)
    column_two_value: dict[str, Any] = Field(default_factory=dict)


class ListEntryCreate(ListEntryBase):
    pass


class ListEntryUpdate(BaseModel):
    sort_index: int | None = None
    column_one_value: dict[str, Any] | None = None
    column_two_value: dict[str, Any] | None = None


class ListEntryRead(ListEntryBase):
    # Built via explicit keyword construction in ListService._entry_read (column_one/two_value
    # need type-aware id translation - see _denormalize_value), not from_attributes.
    id: uuid.UUID
    list_definition_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
