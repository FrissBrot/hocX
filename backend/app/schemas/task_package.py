from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.protocol import _validate_reference_link

RecurrenceType = Literal["once", "monthly", "weekly", "events"]
DueRuleType = Literal["none", "fixed", "offset"]
TodoDeleteMode = Literal["all", "future", "none"]


class TaskPackageResponsible(BaseModel):
    """Ein Verantwortlicher einer Paket-Aufgabe: entweder eine Listenzeile (Ämtli, wird bei
    jeder Erzeugung live aus der Liste aufgelöst) oder eine feste Person."""

    list_definition_id: uuid.UUID | None = None
    list_entry_id: uuid.UUID | None = None
    participant_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _one_source(self) -> TaskPackageResponsible:
        has_list = self.list_definition_id is not None and self.list_entry_id is not None
        if has_list == (self.participant_id is not None):
            raise ValueError("Verantwortliche brauchen entweder eine Listenzeile oder eine Person")
        return self


class TaskPackageRecurrence(BaseModel):
    type: RecurrenceType = "once"
    # monthly: Tag im Monat (zu grosse Werte werden auf den Monatsletzten gekürzt)
    day_of_month: int | None = Field(default=None, ge=1, le=31)
    # weekly: 0 = Montag ... 6 = Sonntag
    weekday: int | None = Field(default=None, ge=0, le=6)
    # events: Termine mit diesem Tag im Zyklus
    event_tag: str | None = None

    @model_validator(mode="after")
    def _required_fields(self) -> TaskPackageRecurrence:
        if self.type == "monthly" and self.day_of_month is None:
            raise ValueError("Monatliche Wiederholung braucht einen Tag im Monat")
        if self.type == "weekly" and self.weekday is None:
            raise ValueError("Wöchentliche Wiederholung braucht einen Wochentag")
        if self.type == "events" and not (self.event_tag or "").strip():
            raise ValueError("Wiederholung pro Termin braucht einen Termin-Tag")
        return self


class TaskPackageDueRule(BaseModel):
    type: DueRuleType = "none"
    # fixed: Tag/Monat innerhalb des Zyklus
    month: int | None = Field(default=None, ge=1, le=12)
    day: int | None = Field(default=None, ge=1, le=31)
    # offset: Tage nach (positiv) bzw. vor (negativ) dem Wiederholungsdatum bzw. Zyklusstart
    offset_days: int | None = Field(default=None, ge=-366, le=366)

    @model_validator(mode="after")
    def _required_fields(self) -> TaskPackageDueRule:
        if self.type == "fixed" and (self.month is None or self.day is None):
            raise ValueError("Festes Fälligkeitsdatum braucht Tag und Monat")
        if self.type == "offset" and self.offset_days is None:
            raise ValueError("Relative Fälligkeit braucht eine Anzahl Tage")
        return self


class TaskPackageItemBase(BaseModel):
    task: str = Field(min_length=1)
    reference_link: str | None = None
    tags: list[str] = []
    responsible: list[TaskPackageResponsible] = []
    recurrence: TaskPackageRecurrence = TaskPackageRecurrence()
    due_rule: TaskPackageDueRule = TaskPackageDueRule()

    _validate_reference_link = field_validator("reference_link")(_validate_reference_link)

    @model_validator(mode="after")
    def _fixed_only_once(self) -> TaskPackageItemBase:
        if self.due_rule.type == "fixed" and self.recurrence.type != "once":
            raise ValueError("Ein festes Fälligkeitsdatum ist nur bei einmal pro Zyklus möglich")
        return self


class TaskPackageItemCreate(TaskPackageItemBase):
    sort_index: int | None = None


class TaskPackageItemUpdate(TaskPackageItemBase):
    sort_index: int | None = None


class TaskPackageItemRead(TaskPackageItemBase):
    id: uuid.UUID
    sort_index: int


class TaskPackageCycleAssign(BaseModel):
    cycle_config_id: uuid.UUID
    # None = laufender Zyklus
    start_cycle_year: int | None = Field(default=None, ge=1900, le=3000)


class TaskPackageCycleRead(BaseModel):
    id: uuid.UUID
    cycle_config_id: uuid.UUID
    cycle_config_name: str
    start_cycle_year: int
    current_cycle_year: int
    current_cycle_label: str


class TaskPackageCreate(BaseModel):
    name: str = Field(min_length=1)
    description: str | None = None
    is_active: bool = True


class TaskPackageUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    description: str | None = None
    is_active: bool | None = None


class TaskPackageRead(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    is_active: bool
    cycles: list[TaskPackageCycleRead] = []
    items: list[TaskPackageItemRead] = []
    open_todo_count: int = 0
    todo_count: int = 0
    created_at: datetime
    updated_at: datetime


class TaskPackagePreviewEntry(BaseModel):
    item_id: uuid.UUID
    task: str
    occurrence_key: str
    occurrence_date: date
    due_date: date | None = None
    assignee_names: list[str] = []
    exists: bool = False


class TaskPackagePreview(BaseModel):
    cycle_config_id: uuid.UUID
    cycle_year: int
    cycle_label: str
    entries: list[TaskPackagePreviewEntry] = []


class TaskPackageSyncResult(BaseModel):
    created: int = 0
    updated: int = 0


class TaskPackageTodoRemovalResult(BaseModel):
    deleted: int = 0
    kept: int = 0
