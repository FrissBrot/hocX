"""Anliegen (agenda_item) - siehe app/services/agenda_item_service.py."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

ScheduleKind = Literal["next_meeting", "month"]
AgendaItemState = Literal["waiting", "scheduled", "treated"]


class AgendaSchedule(BaseModel):
    kind: ScheduleKind = "next_meeting"
    # Beliebiger Tag im gewählten Monat (das Frontend schickt den Monatsersten).
    month: date | None = None

    @model_validator(mode="after")
    def _month_required(self) -> "AgendaSchedule":
        if self.kind == "month" and self.month is None:
            raise ValueError("month is required for kind 'month'")
        return self


class AgendaItemCreate(BaseModel):
    template_id: uuid.UUID
    template_element_id: uuid.UUID | None = None
    title: str = Field(min_length=1, max_length=500)
    body: str | None = Field(default=None, max_length=20000)
    schedule: AgendaSchedule = Field(default_factory=AgendaSchedule)


class AgendaItemUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    body: str | None = Field(default=None, max_length=20000)
    template_id: uuid.UUID | None = None
    template_element_id: uuid.UUID | None = None
    schedule: AgendaSchedule | None = None


class AgendaItemPostpone(BaseModel):
    schedule: AgendaSchedule


class ProtocolAgendaItemCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    body: str | None = Field(default=None, max_length=20000)
    protocol_element_id: uuid.UUID | None = None


class AgendaProtocolRef(BaseModel):
    id: uuid.UUID
    protocol_number: str
    title: str | None = None
    protocol_date: date
    status: str


class AgendaItemRead(BaseModel):
    id: uuid.UUID
    title: str
    body: str | None = None
    template_id: uuid.UUID
    template_name: str
    template_element_id: uuid.UUID | None = None
    template_element_name: str | None = None
    schedule_kind: ScheduleKind
    scheduled_month: date | None = None
    earliest_date: date
    postponed_count: int
    # waiting: noch kein passendes Protokoll · scheduled: erscheint in `protocol` · treated:
    # in `protocol` behandelt (durchgeführt/abgeschlossen)
    state: AgendaItemState
    protocol: AgendaProtocolRef | None = None
    is_bound: bool
    can_edit: bool
    created_by_name: str | None = None
    created_at: datetime
    updated_at: datetime


class ProtocolAgendaItemRead(BaseModel):
    """Anliegen im Protokolleditor - ohne Ersteller."""

    id: uuid.UUID
    title: str
    body: str | None = None
    protocol_element_id: uuid.UUID | None = None
    postponed_count: int
    can_edit: bool


class AgendaTemplatePoint(BaseModel):
    id: uuid.UUID
    name: str


class AgendaTemplateOption(BaseModel):
    id: uuid.UUID
    name: str
    points: list[AgendaTemplatePoint]


class AgendaTemplatePreference(BaseModel):
    template_id: uuid.UUID | None = None
