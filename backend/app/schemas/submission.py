from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

SubmissionSourceType = Literal["events", "list"]
SubmissionElementStatus = Literal["open", "submitted", "reopened"]

SLUG_PATTERN = r"^[a-z0-9-]+$"


class SubmissionAssignmentBase(BaseModel):
    title: str
    description: str | None = None
    source_type: SubmissionSourceType
    tag_filter: str | None = None
    offset_days_before: int | None = Field(default=None, ge=0)
    offset_days_after: int | None = Field(default=None, ge=0)
    list_definition_id: int | None = None
    deadline: date | None = None
    allowed_file_types: list[str] = Field(default_factory=list)
    max_files_per_element: int = Field(default=5, ge=1)
    max_file_size_mb: int = Field(default=20, ge=1)
    is_active: bool = True
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
    list_definition_id: int | None = None
    deadline: date | None = None
    allowed_file_types: list[str] | None = None
    max_files_per_element: int | None = Field(default=None, ge=1)
    max_file_size_mb: int | None = Field(default=None, ge=1)
    is_active: bool | None = None
    responsible_participant_source: str | None = None


class SubmissionAssignmentRead(SubmissionAssignmentBase):
    id: int
    tenant_id: int
    public_slug: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SubmissionFileRead(BaseModel):
    id: int
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
    upload_id: int | None = None
    files: list[SubmissionFileRead] = Field(default_factory=list)
    responsible_participant_id: int | None = None


class SubmissionUploadLogEntry(BaseModel):
    id: int
    element_ref: str
    status: str
    error_message: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
