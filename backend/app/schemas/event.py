from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel


class EventBase(BaseModel):
    event_date: date
    event_end_date: date | None = None
    tag: str | None = None
    title: str
    description: str | None = None
    participant_count: int = 0


class EventCreate(EventBase):
    pass


class EventUpdate(BaseModel):
    event_date: date | None = None
    event_end_date: date | None = None
    tag: str | None = None
    title: str | None = None
    description: str | None = None
    participant_count: int | None = None


class EventRead(EventBase):
    id: int
    tenant_id: int
    event_category_id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
