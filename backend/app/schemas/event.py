from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel


class CycleAssignment(BaseModel):
    cycle_config_id: int
    cycle_year: int

    model_config = {"from_attributes": True}


class EventBase(BaseModel):
    event_date: date
    event_end_date: date | None = None
    tag: str | None = None
    title: str
    description: str | None = None
    participant_count: int = 0
    is_cancelled: bool = False
    organizer_ids: list[int] | None = None
    leadership_ids: list[int] | None = None
    participant_ids: list[int] | None = None
    spezial1_ids: list[int] | None = None
    spezial2_ids: list[int] | None = None
    spezial3_ids: list[int] | None = None
    location: str | None = None
    spezial_text1: str | None = None
    spezial_text2: str | None = None
    spezial_text3: str | None = None


class EventCreate(EventBase):
    cycle_assignments: list[CycleAssignment] | None = None


class EventUpdate(BaseModel):
    event_date: date | None = None
    event_end_date: date | None = None
    tag: str | None = None
    title: str | None = None
    description: str | None = None
    participant_count: int | None = None
    is_cancelled: bool | None = None
    organizer_ids: list[int] | None = None
    leadership_ids: list[int] | None = None
    participant_ids: list[int] | None = None
    spezial1_ids: list[int] | None = None
    spezial2_ids: list[int] | None = None
    spezial3_ids: list[int] | None = None
    location: str | None = None
    spezial_text1: str | None = None
    spezial_text2: str | None = None
    spezial_text3: str | None = None
    cycle_assignments: list[CycleAssignment] | None = None


class EventRead(EventBase):
    id: int
    tenant_id: int
    event_category_id: int
    cycle_assignments: list[CycleAssignment] = []
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


CSV_IMPORT_FIELDS = ("event_date", "event_end_date", "tag", "title", "description", "participant_count")


class EventImportPreviewRow(BaseModel):
    row_number: int
    event_date: str | None = None
    event_end_date: str | None = None
    tag: str | None = None
    title: str | None = None
    description: str | None = None
    participant_count: int | None = None
    error: str | None = None


class EventImportPreview(BaseModel):
    detected_columns: list[str]
    resolved_map: dict[str, str]
    rows: list[EventImportPreviewRow]
    valid_count: int
    error_count: int
