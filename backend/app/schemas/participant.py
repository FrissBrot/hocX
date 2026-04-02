from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class ParticipantBase(BaseModel):
    app_user_id: int | None = None
    first_name: str | None = None
    last_name: str | None = None
    display_name: str
    email: str | None = None
    is_active: bool = True


class ParticipantCreate(ParticipantBase):
    tenant_id: int = 1


class ParticipantUpdate(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    display_name: str | None = None
    email: str | None = None
    is_active: bool | None = None


class ParticipantRead(ParticipantBase):
    id: int
    tenant_id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


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
    participant_ids: list[int]


class ParticipantTemplateAssignmentUpdate(BaseModel):
    template_ids: list[int]


class ParticipantBulkDelete(BaseModel):
    participant_ids: list[int]
