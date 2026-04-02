from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


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
    tenant_id: int = 1


class ListDefinitionUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    column_one_title: str | None = None
    column_one_value_type: ListValueType | None = None
    column_two_title: str | None = None
    column_two_value_type: ListValueType | None = None
    is_active: bool | None = None


class ListDefinitionRead(ListDefinitionBase):
    id: int
    tenant_id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


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
    id: int
    list_definition_id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
