from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, ClassVar

from pydantic import BaseModel, Field, field_validator

from app.models.entities import Tenant
from app.schemas.base import PublicIdModel, reject_nul_characters


class CycleConfigBase(BaseModel):
    name: str
    reset_month: int = Field(default=12, ge=1, le=12)
    reset_day: int = Field(default=31, ge=1, le=31)
    name_pattern: str | None = None


class CycleConfigCreate(CycleConfigBase):
    @field_validator("*")
    @classmethod
    def _no_nul_characters(cls, value: Any) -> Any:
        return reject_nul_characters(value)


class CycleConfigUpdate(BaseModel):
    name: str | None = None
    reset_month: int | None = Field(default=None, ge=1, le=12)
    reset_day: int | None = Field(default=None, ge=1, le=31)
    name_pattern: str | None = None

    @field_validator("*")
    @classmethod
    def _no_nul_characters(cls, value: Any) -> Any:
        return reject_nul_characters(value)


class CycleConfigRead(PublicIdModel, CycleConfigBase):
    _fk_models: ClassVar[dict[str, type]] = {"tenant_id": Tenant}

    id: uuid.UUID
    tenant_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class CycleInfo(BaseModel):
    cycle_year: int
    name: str
