from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import ClassVar, Literal

from pydantic import BaseModel, Field

from app.models.entities import ListDefinition, Tenant
from app.schemas.base import PublicIdModel

SubmissionSourceType = Literal["events", "list"]
SubmissionElementStatus = Literal["open", "submitted", "closed"]
SubmissionSortOrder = Literal["alphabetical", "date", "proximity"]

SLUG_PATTERN = r"^[a-z0-9-]+$"


class SubmissionAssignmentBase(BaseModel):
    title: str
    description: str | None = None
    source_type: SubmissionSourceType
    tag_filter: str | None = None
    offset_days_before: int | None = Field(default=None, ge=0)
    offset_days_after: int | None = Field(default=None, ge=0)
    list_definition_id: uuid.UUID | None = None
    deadline: date | None = None
    allowed_file_types: list[str] = Field(default_factory=list)
    max_files_per_element: int | None = Field(default=5, ge=1)
    max_file_size_mb: int = Field(default=20, ge=1, le=100)
    sort_order: SubmissionSortOrder = "date"
    responsible_participant_source: str | None = None


class SubmissionAssignmentCreate(SubmissionAssignmentBase):
    public_slug: str = Field(pattern=SLUG_PATTERN)


class SubmissionAssignmentUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    public_slug: str | None = Field(default=None, pattern=SLUG_PATTERN)
    source_type: SubmissionSourceType | None = None
    tag_filter: str | None = None
    offset_days_before: int | None = Field(default=None, ge=0)
    offset_days_after: int | None = Field(default=None, ge=0)
    list_definition_id: uuid.UUID | None = None
    deadline: date | None = None
    allowed_file_types: list[str] | None = None
    max_files_per_element: int | None = Field(default=None, ge=1)
    max_file_size_mb: int | None = Field(default=None, ge=1, le=100)
    sort_order: SubmissionSortOrder | None = None
    responsible_participant_source: str | None = None


class SubmissionAssignmentRead(PublicIdModel, SubmissionAssignmentBase):
    _fk_models: ClassVar[dict[str, type]] = {"tenant_id": Tenant, "list_definition_id": ListDefinition}

    id: uuid.UUID
    tenant_id: uuid.UUID
    public_slug: str
    created_at: datetime
    updated_at: datetime


class SubmissionFileRead(BaseModel):
    id: uuid.UUID
    original_name: str
    mime_type: str | None
    file_size_bytes: int | None
    content_url: str
    scan_status: str = "clean"


class SubmissionElementRead(BaseModel):
    element_ref: str
    label: str
    window_start: date | None = None
    window_end: date | None = None
    status: SubmissionElementStatus
    submitted_at: datetime | None = None
    upload_id: uuid.UUID | None = None
    files: list[SubmissionFileRead] = Field(default_factory=list)
    responsible_participant_id: uuid.UUID | None = None


class SubmissionUploadLogEntry(PublicIdModel):
    id: uuid.UUID
    element_ref: str
    status: str
    error_message: str | None = None
    created_at: datetime
