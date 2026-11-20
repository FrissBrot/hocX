from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, ClassVar

from pydantic import BaseModel, Field, field_validator

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

    @field_validator("name", "reset_month", "reset_day")
    @classmethod
    def _reject_explicit_null(cls, value: Any) -> Any:
        # Weglassen ist erlaubt (Teil-Update), ausdrückliches null nicht: die Spalten sind NOT NULL,
        # das UPDATE scheiterte sonst mit IntegrityError (400 plus Eintrag im Fehlerprotokoll).
        # name_pattern darf null sein (Standardname «JJJJ/JJJJ+1»).
        if value is None:
            raise ValueError("must not be null")
        return value


class CycleConfigRead(PublicIdModel, CycleConfigBase):
    _fk_models: ClassVar[dict[str, type]] = {"tenant_id": Tenant}

    id: uuid.UUID
    tenant_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class CycleInfo(BaseModel):
    cycle_year: int
    name: str
