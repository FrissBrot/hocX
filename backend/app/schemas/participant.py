from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import ClassVar

from pydantic import BaseModel, Field, model_validator

from app.models.entities import Tenant
from app.schemas.base import PublicIdModel


class ParticipantBase(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    display_name: str = Field(min_length=1)
    email: str | None = None
    is_active: bool = True
    joined_at: date | None = None
    left_at: date | None = None

    @model_validator(mode="after")
    def _check_date_order(self) -> "ParticipantBase":
        if self.joined_at is not None and self.left_at is not None and self.left_at < self.joined_at:
            raise ValueError("left_at must not be before joined_at")
        return self


class ParticipantCreate(ParticipantBase):
    pass


class ParticipantUpdate(BaseModel):
    login_enabled: bool | None = None
    password: str | None = Field(default=None, min_length=12)
    # Rollen setzen (nur mit access.manage, siehe routes/participants.py).
    role_ids: list[uuid.UUID] | None = Field(default=None, max_length=50)
    first_name: str | None = None
    last_name: str | None = None
    display_name: str | None = None
    email: str | None = None
    is_active: bool | None = None
    joined_at: date | None = None
    left_at: date | None = None

    @model_validator(mode="after")
    def _check_date_order(self) -> "ParticipantUpdate":
        if self.joined_at is not None and self.left_at is not None and self.left_at < self.joined_at:
            raise ValueError("left_at must not be before joined_at")
        return self


class ParticipantRead(PublicIdModel, ParticipantBase):
    _fk_models: ClassVar[dict[str, type]] = {"tenant_id": Tenant}

    login_enabled: bool = False
    id: uuid.UUID
    tenant_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class TemplateParticipantAssignment(BaseModel):
    participant_id: uuid.UUID
    exclude_from_attendance: bool = False


class TemplateParticipantAssignmentRead(ParticipantRead):
    exclude_from_attendance: bool = False


class ParticipantImportRow(BaseModel):
    display_name: str
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None


class ParticipantImportResult(BaseModel):
    imported: list[ParticipantRead]
    duplicates: list[str]
    errors: list[str]


class TemplateParticipantAssignmentUpdate(BaseModel):
    participant_ids: list[uuid.UUID] = Field(default_factory=list)
    participants: list[TemplateParticipantAssignment] | None = None


class ParticipantTemplateAssignmentUpdate(BaseModel):
    template_ids: list[uuid.UUID]


class ParticipantBulkDelete(BaseModel):
    participant_ids: list[uuid.UUID]
