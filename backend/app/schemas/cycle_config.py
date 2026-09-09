from __future__ import annotations

import uuid
from datetime import datetime
from typing import ClassVar

from pydantic import BaseModel, Field

from app.models.entities import Tenant
from app.schemas.base import PublicIdModel


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


class CycleConfigRead(PublicIdModel, CycleConfigBase):
    _fk_models: ClassVar[dict[str, type]] = {"tenant_id": Tenant}

    id: uuid.UUID
    tenant_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class CycleInfo(BaseModel):
    cycle_year: int
    name: str
