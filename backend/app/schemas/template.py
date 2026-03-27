from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class TemplateBase(BaseModel):
    name: str
    description: str | None = None
    version: int = Field(default=1, ge=1)
    status: str = "active"
    document_template_id: int | None = None


class TemplateCreate(TemplateBase):
    tenant_id: int = 1
    created_by: int | None = None


class TemplateUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    version: int | None = Field(default=None, ge=1)
    status: str | None = None
    document_template_id: int | None = None


class TemplateRead(TemplateBase):
    id: int
    tenant_id: int
    created_by: int | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ElementDefinitionBase(BaseModel):
    tenant_id: int = 1
    element_type_id: int
    render_type_id: int
    title: str
    display_title: str | None = None
    description: str | None = None
    is_editable: bool = True
    allows_multiple_values: bool = False
    export_visible: bool = True
    latex_template: str | None = None
    configuration_json: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True


class ElementDefinitionCreate(ElementDefinitionBase):
    pass


class ElementDefinitionUpdate(BaseModel):
    element_type_id: int | None = None
    render_type_id: int | None = None
    title: str | None = None
    display_title: str | None = None
    description: str | None = None
    is_editable: bool | None = None
    allows_multiple_values: bool | None = None
    export_visible: bool | None = None
    latex_template: str | None = None
    configuration_json: dict[str, Any] | None = None
    is_active: bool | None = None


class ElementDefinitionRead(ElementDefinitionBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TemplateElementBase(BaseModel):
    element_definition_id: int
    sort_index: int
    render_order: int | None = None
    section_name: str | None = None
    section_order: int | None = None
    is_required: bool = False
    is_visible: bool = True
    export_visible: bool = True
    heading_text: str | None = None
    configuration_override_json: dict[str, Any] = Field(default_factory=dict)


class TemplateElementCreate(TemplateElementBase):
    pass


class TemplateElementUpdate(BaseModel):
    element_definition_id: int | None = None
    sort_index: int | None = None
    render_order: int | None = None
    section_name: str | None = None
    section_order: int | None = None
    is_required: bool | None = None
    is_visible: bool | None = None
    export_visible: bool | None = None
    heading_text: str | None = None
    configuration_override_json: dict[str, Any] | None = None


class TemplateElementRead(TemplateElementBase):
    id: int
    template_id: int
    created_at: datetime

    model_config = {"from_attributes": True}
