from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class PublicMaintenanceUpcoming(BaseModel):
    starts_at: datetime | None
    ends_at: datetime | None
    kind: str
    reason_code: str
    messages: dict[str, str] = Field(default_factory=dict)


class PublicMaintenanceStatus(BaseModel):
    """Bewusst minimal: keine Job-IDs, Profil-/Bucket-Namen oder Fehlertexte."""

    active: bool
    partial: bool
    block_scope: str | None = None
    reason_code: str | None = None
    messages: dict[str, str] = Field(default_factory=dict)
    affected_features: list[str] = Field(default_factory=list)
    started_at: datetime | None = None
    estimate_state: Literal["estimating", "estimated", "overdue"] | None = None
    estimated_end_at: datetime | None = None
    remaining_low_seconds: int | None = None
    remaining_high_seconds: int | None = None
    upcoming: list[PublicMaintenanceUpcoming] = Field(default_factory=list)
    updated_at: datetime


class MaintenanceConditionRead(BaseModel):
    key: str
    satisfied: bool
    reason: str
    params: dict[str, Any] = Field(default_factory=dict)


class MaintenanceEventRead(BaseModel):
    id: int
    created_at: datetime
    kind: str
    actor_email: str | None
    from_state: str | None
    to_state: str | None
    details: dict[str, Any]

    model_config = {"from_attributes": True}


class MaintenanceWindowRead(BaseModel):
    id: uuid.UUID
    kind: str
    block_scope: str
    state: str
    reason_code: str
    affected_features: list[str]
    public_message: dict[str, str]
    internal_note: str | None
    source_job_type: str | None
    source_job_id: str | None
    scheduled_start_at: datetime | None
    scheduled_end_at: datetime | None
    started_at: datetime | None
    ended_at: datetime | None
    estimate: dict[str, Any] | None
    estimated_end_at: datetime | None
    original_estimated_end_at: datetime | None
    safety_margin_seconds: int | None
    estimate_updated_at: datetime | None
    progress: dict[str, Any]
    release_conditions: list[dict[str, Any]]
    warnings: list[Any]
    last_error: str | None
    created_by_email: str | None
    created_at: datetime
    updated_at: datetime
    conditions: list[MaintenanceConditionRead] = Field(default_factory=list)
    events: list[MaintenanceEventRead] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class MaintenanceOverview(BaseModel):
    blocking: bool
    full_active: bool
    current: list[MaintenanceWindowRead]
    scheduled: list[MaintenanceWindowRead]
    history: list[MaintenanceWindowRead]
    history_total: int


class MaintenanceCreate(BaseModel):
    kind: Literal["full", "partial"] = "full"
    block_scope: Literal["all", "writes", "uploads"] = "all"
    affected_features: list[str] = Field(default_factory=list, max_length=10)
    public_message: dict[str, str] = Field(default_factory=dict)
    internal_note: str | None = Field(default=None, max_length=4000)
    scheduled_start_at: datetime | None = None
    scheduled_end_at: datetime | None = None
    # True = sofort kontrolliert starten (preparing -> active), sonst geplant.
    start_now: bool = False


class MaintenanceUpdate(BaseModel):
    public_message: dict[str, str] | None = None
    internal_note: str | None = Field(default=None, max_length=4000)
    scheduled_start_at: datetime | None = None
    scheduled_end_at: datetime | None = None
