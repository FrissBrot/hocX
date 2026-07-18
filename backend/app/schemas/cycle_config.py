from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class CycleConfigBase(BaseModel):
    name: str
    reset_month: int = Field(default=12, ge=1, le=12)
    reset_day: int = Field(default=31, ge=1, le=31)
    name_pattern: str | None = None


class CycleConfigCreate(CycleConfigBase):
    pass


class CycleConfigUpdate(BaseModel):
    name: str | None = None
    reset_month: int | None = Field(default=None, ge=1, le=12)
    reset_day: int | None = Field(default=None, ge=1, le=31)
    name_pattern: str | None = None


class CycleConfigRead(CycleConfigBase):
    id: int
    tenant_id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CycleInfo(BaseModel):
    cycle_year: int
    name: str
