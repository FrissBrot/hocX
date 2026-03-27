from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class DocumentTemplatePartBase(BaseModel):
    tenant_id: int = 1
    code: str
    name: str
    part_type: str
    description: str | None = None
    version: int = Field(default=1, ge=1)
    is_active: bool = True


class DocumentTemplatePartCreate(DocumentTemplatePartBase):
    pass


class DocumentTemplatePartUpdate(BaseModel):
    code: str | None = None
    name: str | None = None
    part_type: str | None = None
    description: str | None = None
    version: int | None = Field(default=None, ge=1)
    is_active: bool | None = None


class DocumentTemplatePartRead(DocumentTemplatePartBase):
    id: int
    storage_path: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DocumentTemplateBase(BaseModel):
    tenant_id: int = 1
    code: str
    name: str
    description: str | None = None
    version: int = Field(default=1, ge=1)
    is_active: bool = True
    is_default: bool = False
    configuration_json: dict[str, Any] = Field(default_factory=dict)


class DocumentTemplateCreate(DocumentTemplateBase):
    pass


class DocumentTemplateUpdate(BaseModel):
    code: str | None = None
    name: str | None = None
    description: str | None = None
    version: int | None = Field(default=None, ge=1)
    is_active: bool | None = None
    is_default: bool | None = None
    configuration_json: dict[str, Any] | None = None


class DocumentTemplateRead(DocumentTemplateBase):
    id: int
    filesystem_path: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
