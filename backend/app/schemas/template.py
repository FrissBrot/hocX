from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field

from app.models.entities import AppUser, CycleConfig, DocumentTemplate, Event, Tenant
from app.schemas.base import PublicIdModel
from app.schemas.cycle_config import CycleConfigRead


class TemplateBase(BaseModel):
    name: str
    description: str | None = None
    version: int = Field(default=1, ge=1)
    status: str = "active"
    document_template_id: uuid.UUID | None = None
    next_event_id: uuid.UUID | None = None
    last_event_id: uuid.UUID | None = None
    todo_due_event_tag: str | None = None
    protocol_number_pattern: str | None = None
    title_pattern: str | None = None
    auto_create_next_protocol: bool = False
    cycle_config_id: uuid.UUID | None = None


class TemplateCreate(TemplateBase):
    pass


class TemplateUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    version: int | None = Field(default=None, ge=1)
    status: str | None = None
    document_template_id: uuid.UUID | None = None
    next_event_id: uuid.UUID | None = None
    last_event_id: uuid.UUID | None = None
    todo_due_event_tag: str | None = None
    protocol_number_pattern: str | None = None
    title_pattern: str | None = None
    auto_create_next_protocol: bool | None = None
    cycle_config_id: uuid.UUID | None = None


class TemplateDuplicateRequest(BaseModel):
    name: str


class TemplateRead(PublicIdModel, TemplateBase):
    _fk_models: ClassVar[dict[str, type]] = {
        "tenant_id": Tenant,
        "document_template_id": DocumentTemplate,
        "next_event_id": Event,
        "last_event_id": Event,
        "cycle_config_id": CycleConfig,
        "created_by": AppUser,
    }

    id: uuid.UUID
    tenant_id: uuid.UUID
    cycle_config: CycleConfigRead | None = None
    created_by: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime


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
    # Built via explicit keyword construction in ElementDefinitionService._read_model, not
    # from_attributes on a raw ORM object (blocks live inside a JSONB column, not a table) -
    # id/tenant_id are set from entity.public_id/tenant public_id there directly, so no
    # PublicIdModel/_fk_models machinery is needed on this class.
    id: uuid.UUID
    tenant_id: uuid.UUID
    title: str
    description: str | None = None
    is_active: bool
    blocks: list[ElementDefinitionBlockRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class TemplateElementBlockRead(BaseModel):
    # id/element_definition_block_id are the client-owned opaque ids living inside
    # ElementDefinition.configuration_json["blocks"][].id (see ElementDefinitionBlockBase) -
    # not a database row/FK, so deliberately left as plain int, unaffected by the public_id
    # migration.
    id: int
    template_element_id: uuid.UUID
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
    element_definition_id: uuid.UUID
    sort_index: int
    configuration_json: dict[str, Any] = Field(default_factory=dict)


class TemplateElementUpdate(BaseModel):
    sort_index: int | None = None
    configuration_json: dict[str, Any] | None = None


class TemplateElementRead(BaseModel):
    # Built via explicit keyword construction in TemplateElementService._read_model (joins
    # TemplateElement with its ElementDefinition) - see ElementDefinitionRead's identical note.
    id: uuid.UUID
    template_id: uuid.UUID
    element_definition_id: uuid.UUID
    sort_index: int
    title: str
    description: str | None = None
    configuration_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    blocks: list[TemplateElementBlockRead] = Field(default_factory=list)
    behavior: dict[str, bool] = Field(default_factory=dict)


class TemplateElementBehaviorUpdate(BaseModel):
    scope: Literal["element", "block"]
    block_id: int | None = None
    is_editable: bool | None = None
    is_visible: bool | None = None
    export_visible: bool | None = None
    copy_from_last_protocol: bool | None = None
    title_as_subtitle: bool | None = None
