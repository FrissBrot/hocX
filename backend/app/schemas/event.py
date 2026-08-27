from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy.orm import object_session

from app.models.entities import CycleConfig, Participant, Tenant
from app.schemas.base import PublicIdModel
from app.services import public_id_service

_PARTICIPANT_ID_FIELDS = (
    "organizer_ids",
    "leadership_ids",
    "participant_ids",
    "spezial1_ids",
    "spezial2_ids",
    "spezial3_ids",
)


class CycleAssignment(BaseModel):
    # EventCycle (the join row this is read from) has no public_id of its own (composite
    # PK, out of the public_id migration's scope) - resolve cycle_config_id explicitly
    # via the same session the source row is attached to, same technique as PublicIdModel.
    cycle_config_id: uuid.UUID
    cycle_year: int

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def _resolve_cycle_config_id(cls, data: Any) -> Any:
        if isinstance(data, dict) or not hasattr(data, "cycle_config_id"):
            return data
        db = object_session(data)
        return {
            "cycle_config_id": public_id_service.resolve_public_id(db, CycleConfig, data.cycle_config_id),
            "cycle_year": data.cycle_year,
        }


class EventBase(BaseModel):
    event_date: date
    event_end_date: date | None = None
    tag: str | None = None
    title: str
    description: str | None = None
    participant_count: int = 0
    is_cancelled: bool = False
    organizer_ids: list[uuid.UUID] | None = None
    leadership_ids: list[uuid.UUID] | None = None
    participant_ids: list[uuid.UUID] | None = None
    spezial1_ids: list[uuid.UUID] | None = None
    spezial2_ids: list[uuid.UUID] | None = None
    spezial3_ids: list[uuid.UUID] | None = None
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
    organizer_ids: list[uuid.UUID] | None = None
    leadership_ids: list[uuid.UUID] | None = None
    participant_ids: list[uuid.UUID] | None = None
    spezial1_ids: list[uuid.UUID] | None = None
    spezial2_ids: list[uuid.UUID] | None = None
    spezial3_ids: list[uuid.UUID] | None = None
    location: str | None = None
    spezial_text1: str | None = None
    spezial_text2: str | None = None
    spezial_text3: str | None = None
    cycle_assignments: list[CycleAssignment] | None = None


class EventRead(PublicIdModel, EventBase):
    _fk_models: ClassVar[dict[str, type]] = {"tenant_id": Tenant}
    _fk_list_models: ClassVar[dict[str, type]] = {field: Participant for field in _PARTICIPANT_ID_FIELDS}

    id: uuid.UUID
    tenant_id: uuid.UUID
    # Lookup-table code, deliberately kept as a small numeric id (not migrated - see the
    # public_id migration's excluded-tables list).
    event_category_id: int
    cycle_assignments: list[CycleAssignment] = []
    created_at: datetime
    updated_at: datetime


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
