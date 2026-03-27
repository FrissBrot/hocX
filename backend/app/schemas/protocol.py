from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel


class ProtocolCreateFromTemplate(BaseModel):
    tenant_id: int = 1
    template_id: int
    protocol_number: str
    protocol_date: date
    created_by: int | None = None
    title: str | None = None
    event_id: int | None = None


class ProtocolUpdate(BaseModel):
    title: str | None = None
    protocol_date: date | None = None
    event_id: int | None = None
    status: str | None = None


class ProtocolRead(BaseModel):
    id: int
    tenant_id: int
    template_id: int
    template_version: int
    protocol_number: str
    title: str | None = None
    protocol_date: date
    event_id: int | None = None
    status: str
    created_by: int | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProtocolElementRead(BaseModel):
    id: int
    protocol_id: int
    template_element_id: int | None = None
    element_definition_id: int | None = None
    element_type_id: int
    render_type_id: int
    element_type_code: str | None = None
    render_type_code: str | None = None
    title_snapshot: str
    display_title_snapshot: str | None = None
    description_snapshot: str | None = None
    is_editable_snapshot: bool
    allows_multiple_values_snapshot: bool
    sort_index: int
    render_order: int | None = None
    section_name_snapshot: str | None = None
    section_order_snapshot: int | None = None
    is_required_snapshot: bool
    is_visible_snapshot: bool
    export_visible_snapshot: bool
    heading_text_snapshot: str | None = None
    latex_template_snapshot: str | None = None
    configuration_snapshot_json: dict
    text_content: str | None = None
    display_compiled_text: str | None = None
    display_snapshot_json: dict | None = None


class ProtocolElementUpdate(BaseModel):
    title_snapshot: str | None = None
    display_title_snapshot: str | None = None
    description_snapshot: str | None = None
    is_editable_snapshot: bool | None = None
    allows_multiple_values_snapshot: bool | None = None
    render_order: int | None = None
    section_name_snapshot: str | None = None
    section_order_snapshot: int | None = None
    is_required_snapshot: bool | None = None
    is_visible_snapshot: bool | None = None
    export_visible_snapshot: bool | None = None
    heading_text_snapshot: str | None = None
    latex_template_snapshot: str | None = None
    configuration_snapshot_json: dict | None = None


class ProtocolTextUpdate(BaseModel):
    content: str


class ProtocolTextRead(BaseModel):
    protocol_element_id: int
    content: str
    status: str


class ProtocolTodoCreate(BaseModel):
    task: str
    assigned_user_id: int | None = None
    todo_status_id: int = 1
    due_date: date | None = None
    reference_link: str | None = None
    created_by: int | None = None


class ProtocolTodoUpdate(BaseModel):
    task: str | None = None
    assigned_user_id: int | None = None
    todo_status_id: int | None = None
    due_date: date | None = None
    completed_at: datetime | None = None
    reference_link: str | None = None


class ProtocolTodoRead(BaseModel):
    id: int
    protocol_element_id: int
    sort_index: int
    task: str
    assigned_user_id: int | None = None
    todo_status_id: int
    todo_status_code: str | None = None
    due_date: date | None = None
    completed_at: datetime | None = None
    reference_link: str | None = None
    created_by: int | None = None
    created_at: datetime
    updated_at: datetime


class ProtocolImageRead(BaseModel):
    id: int
    protocol_element_id: int
    stored_file_id: int
    sort_index: int
    title: str | None = None
    caption: str | None = None
    original_name: str
    mime_type: str | None = None
    file_size_bytes: int | None = None
    content_url: str
