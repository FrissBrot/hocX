from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.cycle_config import CycleConfigRead


class TemplateBase(BaseModel):
    name: str
    description: str | None = None
    version: int = Field(default=1, ge=1)
    status: str = "active"
    document_template_id: int | None = None
    next_event_id: int | None = None
    last_event_id: int | None = None
    todo_due_event_tag: str | None = None
    protocol_number_pattern: str | None = None
    title_pattern: str | None = None
    auto_create_next_protocol: bool = False
    cycle_config_id: int | None = None


class TemplateCreate(TemplateBase):
    created_by: int | None = None


class TemplateUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    version: int | None = Field(default=None, ge=1)
    status: str | None = None
    document_template_id: int | None = None
    next_event_id: int | None = None
    last_event_id: int | None = None
    todo_due_event_tag: str | None = None
    protocol_number_pattern: str | None = None
    title_pattern: str | None = None
    auto_create_next_protocol: bool | None = None
    cycle_config_id: int | None = None


class TemplateDuplicateRequest(BaseModel):
    name: str


class TemplateRead(TemplateBase):
    id: int
    tenant_id: int
    cycle_config: CycleConfigRead | None = None
    created_by: int | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TemplateParticipantRead(BaseModel):
    id: int
    template_id: int
    participant_id: int
    created_at: datetime


class ElementDefinitionBlockBase(BaseModel):
    id: int
    title: str
    description: str | None = None
    block_title: str | None = None
    default_content: str | None = None
    copy_from_last_protocol: bool = False
    element_type_id: int
    render_type_id: int
    is_editable: bool = True
    allows_multiple_values: bool = False
    export_visible: bool = True
    is_visible: bool = True
    sort_index: int
    render_order: int | None = None
    latex_template: str | None = None
    configuration_json: dict[str, Any] = Field(default_factory=dict)


class ElementDefinitionBlockCreate(ElementDefinitionBlockBase):
    pass


class ElementDefinitionBlockRead(ElementDefinitionBlockBase):
    pass


class ElementDefinitionBase(BaseModel):
    title: str
    description: str | None = None
    is_active: bool = True
    blocks: list[ElementDefinitionBlockCreate] = Field(default_factory=list)


class ElementDefinitionCreate(ElementDefinitionBase):
    pass


class ElementDefinitionUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    is_active: bool | None = None
    blocks: list[ElementDefinitionBlockCreate] | None = None


class ElementDefinitionRead(BaseModel):
    id: int
    tenant_id: int
    title: str
    description: str | None = None
    is_active: bool
    blocks: list[ElementDefinitionBlockRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TemplateElementBlockRead(BaseModel):
    id: int
    template_element_id: int
    element_definition_block_id: int | None = None
    title: str
    description: str | None = None
    block_title: str | None = None
    default_content: str | None = None
    element_type_id: int
    render_type_id: int
    is_editable: bool
    allows_multiple_values: bool
    export_visible: bool
    is_visible: bool
    title_as_subtitle: bool = True
    copy_from_last_protocol: bool = False
    sort_index: int
    render_order: int | None = None
    latex_template: str | None = None
    configuration_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class TemplateElementCreate(BaseModel):
    element_definition_id: int
    sort_index: int
    configuration_json: dict[str, Any] = Field(default_factory=dict)


class TemplateElementUpdate(BaseModel):
    sort_index: int | None = None
    configuration_json: dict[str, Any] | None = None


class TemplateElementRead(BaseModel):
    id: int
    template_id: int
    element_definition_id: int
    sort_index: int
    title: str
    description: str | None = None
    configuration_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    blocks: list[TemplateElementBlockRead] = Field(default_factory=list)
    behavior: dict[str, bool] = Field(default_factory=dict)

    model_config = {"from_attributes": True}


class TemplateElementBehaviorUpdate(BaseModel):
    scope: Literal["element", "block"]
    block_id: int | None = None
    is_editable: bool | None = None
    is_visible: bool | None = None
    export_visible: bool | None = None
    copy_from_last_protocol: bool | None = None
    title_as_subtitle: bool | None = None
