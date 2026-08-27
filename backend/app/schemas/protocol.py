from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import ClassVar, Literal

from pydantic import BaseModel, Field, field_validator

from app.models.entities import AppUser, DocumentTemplate, Event, Template, Tenant
from app.schemas.base import PublicIdModel
from app.schemas.event import EventRead

# Mirrors the DB's ck_protocol_status CHECK constraint (models/entities.py) and
# ProtocolService._STATUS_ORDER - the full, ordered protocol lifecycle.
ProtocolStatus = Literal["geplant", "vorbereitet", "durchgeführt", "abgeschlossen"]


def _validate_reference_link(value: str | None) -> str | None:
    """Erlaubt nur leere Werte oder Links mit http(s):// als Schema.

    Verhindert Stored XSS ueber z.B. javascript:-URIs, die sonst als
    href in <a>-Tags im Frontend landen wuerden.
    """
    if value is None or value == "":
        return value
    if not value.lower().startswith(("http://", "https://")):
        raise ValueError("reference_link muss mit http:// oder https:// beginnen")
    return value


class ProtocolCreateFromTemplate(BaseModel):
    # UUIDs as received from the client - the router resolves these to internal ids
    # (see app.services.public_id_service) before calling into ProtocolService.
    template_id: uuid.UUID
    document_template_id: uuid.UUID | None = None
    protocol_number: str | None = None
    protocol_date: date
    title: str | None = None
    event_id: uuid.UUID | None = None


class ProtocolUpdate(BaseModel):
    title: str | None = None
    protocol_date: date | None = None
    event_id: uuid.UUID | None = None
    status: ProtocolStatus | None = None
    document_template_id: uuid.UUID | None = None
    session_notes: str | None = None
    expected_session_notes: str | None = None
    track_changes_enabled: bool | None = None


class ProtocolRead(PublicIdModel):
    _fk_models: ClassVar[dict[str, type]] = {
        "tenant_id": Tenant,
        "template_id": Template,
        "document_template_id": DocumentTemplate,
        "event_id": Event,
        "created_by": AppUser,
    }

    id: uuid.UUID
    tenant_id: uuid.UUID
    template_id: uuid.UUID
    template_version: int
    document_template_id: uuid.UUID | None = None
    document_template_version: int | None = None
    protocol_number: str
    title: str | None = None
    protocol_date: date
    event_id: uuid.UUID | None = None
    status: str
    version_major: int = 0
    version_minor: int = 0
    version_final_minor: int = 0
    session_notes: str | None = None
    track_changes_enabled: bool = False
    created_by: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
    latest_pdf_url: str | None = None
    # Set when this protocol was created via the Word-Import queue (/tools/import) -
    # lets the UI show an "Importiert" badge + a link back to the source .docx/.pdf.
    import_source_filename: str | None = None
    import_source_url: str | None = None


class NextSessionAttendanceEntry(BaseModel):
    participant_id: uuid.UUID
    participant_name: str
    status: str


class NextSessionRead(BaseModel):
    protocol: ProtocolRead | None = None
    attendance_block_id: uuid.UUID | None = None
    entries: list[NextSessionAttendanceEntry] = Field(default_factory=list)


class ProtocolCycleInfo(BaseModel):
    cycle_config_id: uuid.UUID
    cycle_year: int
    label: str


class ProtocolCycleEventsRead(BaseModel):
    items: list[EventRead]
    total: int
    cycle: ProtocolCycleInfo | None = None


class AttendanceExcusePayload(BaseModel):
    excused: bool = True


class ProtocolElementBlockRead(BaseModel):
    # Built via explicit keyword construction (protocol_elements.py's _block_to_read) - not
    # from_attributes, so id/protocol_element_id/template_element_block_id/
    # element_definition_id are resolved to public UUIDs there directly. element_type_id/
    # render_type_id are lookup-table codes, deliberately kept as small numeric ids.
    id: uuid.UUID
    protocol_element_id: uuid.UUID
    template_element_block_id: uuid.UUID | None = None
    element_definition_id: uuid.UUID | None = None
    element_type_id: int
    render_type_id: int
    element_type_code: str | None = None
    render_type_code: str | None = None
    title_snapshot: str
    display_title_snapshot: str | None = None
    description_snapshot: str | None = None
    block_title_snapshot: str | None = None
    copy_from_last_protocol: bool = False
    is_editable_snapshot: bool
    allows_multiple_values_snapshot: bool
    sort_index: int
    render_order: int | None = None
    is_required_snapshot: bool
    is_visible_snapshot: bool
    export_visible_snapshot: bool
    latex_template_snapshot: str | None = None
    configuration_snapshot_json: dict
    text_content: str | None = None
    display_compiled_text: str | None = None
    display_snapshot_json: dict | None = None
    tracked_dirty: bool = False
    tracked_baseline_content: str | None = None


class ProtocolElementRead(BaseModel):
    # Built via explicit keyword construction (protocol_element_service.py) - see
    # ProtocolElementBlockRead's identical note.
    id: uuid.UUID
    protocol_id: uuid.UUID
    template_element_id: uuid.UUID | None = None
    sort_index: int
    section_name_snapshot: str
    section_order_snapshot: int | None = None
    is_required_snapshot: bool
    is_visible_snapshot: bool
    export_visible_snapshot: bool
    show_when_empty: bool = False
    blocks: list[ProtocolElementBlockRead] = Field(default_factory=list)


class ProtocolElementUpdate(BaseModel):
    sort_index: int | None = None
    section_name_snapshot: str | None = None
    section_order_snapshot: int | None = None
    is_required_snapshot: bool | None = None
    is_visible_snapshot: bool | None = None
    export_visible_snapshot: bool | None = None


class ProtocolElementBlockUpdate(BaseModel):
    block_title_snapshot: str | None = None
    description_snapshot: str | None = None
    sort_index: int | None = None
    render_order: int | None = None
    is_required_snapshot: bool | None = None
    is_visible_snapshot: bool | None = None
    export_visible_snapshot: bool | None = None
    configuration_snapshot_json: dict | None = None


class ProtocolElementBlockFromEventCreate(BaseModel):
    event_id: uuid.UUID


class QuickTodoCreate(BaseModel):
    task: str
    tag: str = "Sitzungsnotizen"


class ProtocolTextUpdate(BaseModel):
    content: str
    # Optimistic concurrency: clients send the last server value they edited from. Omitted
    # for backwards compatibility with older clients and internal callers.
    expected_content: str | None = None


class ProtocolTextRead(BaseModel):
    protocol_element_block_id: uuid.UUID
    content: str
    status: str
    tracked_dirty: bool = False
    tracked_baseline_content: str | None = None


class ProtocolTodoCreate(BaseModel):
    task: str
    assigned_user_id: uuid.UUID | None = None
    assigned_participant_id: uuid.UUID | None = None
    todo_status_id: int = 1
    due_date: date | None = None
    due_event_id: uuid.UUID | None = None
    due_marker: str | None = None
    reference_link: str | None = None
    tags: list[str] = []
    created_by: uuid.UUID | None = None

    _validate_reference_link = field_validator("reference_link")(_validate_reference_link)


class ProtocolTodoUpdate(BaseModel):
    task: str | None = None
    assigned_user_id: uuid.UUID | None = None
    assigned_participant_id: uuid.UUID | None = None
    todo_status_id: int | None = None
    due_date: date | None = None
    due_event_id: uuid.UUID | None = None
    due_marker: str | None = None
    completed_at: datetime | None = None
    reference_link: str | None = None
    tags: list[str] | None = None
    closed_in_protocol_id: uuid.UUID | None = None

    _validate_reference_link = field_validator("reference_link")(_validate_reference_link)


class ProtocolTodoRead(BaseModel):
    # Built via explicit keyword construction in ProtocolTodoService (joined query rows,
    # not a plain ORM object) - see _common_fields, which resolves every FK field below.
    id: uuid.UUID
    protocol_element_block_id: uuid.UUID | None = None
    sort_index: int
    task: str
    assigned_user_id: uuid.UUID | None = None
    assigned_participant_id: uuid.UUID | None = None
    assigned_participant_name: str | None = None
    todo_status_id: int
    todo_status_code: str | None = None
    due_date: date | None = None
    due_event_id: uuid.UUID | None = None
    due_event_title: str | None = None
    due_event_date: date | None = None
    due_marker: str | None = None
    resolved_due_date: date | None = None
    resolved_due_label: str | None = None
    completed_at: datetime | None = None
    reference_link: str | None = None
    tags: list[str] = []
    created_by: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
    closed_in_protocol_id: uuid.UUID | None = None
    tracked_change: str | None = None
    tracked_change_before_json: dict | None = None
    pending_delete: bool = False

    _validate_reference_link_read = field_validator("reference_link")(_validate_reference_link)


class TodoListItem(ProtocolTodoRead):
    protocol_id: uuid.UUID | None = None
    protocol_number: str | None = None
    protocol_date: date | None = None
    protocol_title: str | None = None
    protocol_status: str | None = None
    block_title: str | None = None
    submission_assignment_id: uuid.UUID | None = None
    element_ref: str | None = None


class ProtocolImageRead(BaseModel):
    # Built via explicit keyword construction in FileService (joins ProtocolImage with its
    # StoredFile) - id/protocol_element_block_id/stored_file_id are set from the respective
    # rows' public_id there directly.
    id: uuid.UUID
    protocol_element_block_id: uuid.UUID
    stored_file_id: uuid.UUID
    sort_index: int
    title: str | None = None
    caption: str | None = None
    original_name: str
    mime_type: str | None = None
    file_size_bytes: int | None = None
    content_url: str


class ProtocolExportRead(BaseModel):
    # None for a "global" export (todos/list/events spanning the whole tenant, not tied
    # to one protocol) - was the sentinel protocol_id=0 before the public_id migration.
    protocol_id: uuid.UUID | None = None
    export_format: str
    generated_file_id: uuid.UUID | None = None
    content_url: str | None = None
    storage_path: str | None = None
    created_at: datetime | None = None
    status: str
    version_major: int | None = None
    version_minor: int | None = None


class MarkdownExportRead(BaseModel):
    content: str
