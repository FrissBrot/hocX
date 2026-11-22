from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import ClassVar, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.entities import Tenant
from app.schemas.base import PublicIdModel, clean_display_name, reject_null
from app.schemas.role import RoleRef


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
    _clean_display_name = field_validator("display_name")(clean_display_name)


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
    # E-Mail-Benachrichtigungen für Personen ohne Login (Migration 0170) - nur der Admin schaltet sie ein.
    notify_without_login: bool | None = None

    _clean_display_name = field_validator("display_name")(clean_display_name)
    _reject_null = field_validator("is_active")(reject_null)

    @model_validator(mode="after")
    def _check_date_order(self) -> "ParticipantUpdate":
        if self.joined_at is not None and self.left_at is not None and self.left_at < self.joined_at:
            raise ValueError("left_at must not be before joined_at")
        return self


class ParticipantRead(PublicIdModel, ParticipantBase):
    _fk_models: ClassVar[dict[str, type]] = {"tenant_id": Tenant}

    login_enabled: bool = False
    notify_without_login: bool = False
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
    # Zeilennummern (als Text) nicht importierbarer Zeilen; die Oberfläche übersetzt die Meldung.
    errors: list[str]


# Obergrenze für ID-Listen ohne eigene Grenze: so viele Personen, wie GET /participants höchstens
# liefert (limit le=2000). Ohne Grenze sprengten > 65 535 IDs die Parametergrenze von PostgreSQL
# in resolve_internal_ids (500 statt 422, Bug-Bounty 2026-11-22).
MAX_PARTICIPANT_ID_LIST = 2000


class TemplateParticipantAssignmentUpdate(BaseModel):
    participant_ids: list[uuid.UUID] = Field(default_factory=list, max_length=MAX_PARTICIPANT_ID_LIST)
    participants: list[TemplateParticipantAssignment] | None = Field(default=None, max_length=MAX_PARTICIPANT_ID_LIST)


class ParticipantTemplateAssignmentUpdate(BaseModel):
    template_ids: list[uuid.UUID] = Field(max_length=MAX_PARTICIPANT_ID_LIST)


class ParticipantBulkDelete(BaseModel):
    participant_ids: list[uuid.UUID] = Field(max_length=MAX_PARTICIPANT_ID_LIST)


class ParticipantInviteRead(BaseModel):
    """Offene Einladung per E-Mail (notifications/account.py). sent_at/expires_at erst nach Versand."""

    participant_id: uuid.UUID
    created_at: datetime
    sent_at: datetime | None = None
    expires_at: datetime | None = None


class ParticipantOverviewRead(ParticipantRead):
    """Mitgliederliste und Personenseite (Konzept «Personen an einem Ort»): zusätzlich Login-Status,
    Rollen und Bussentarif. tariff_id nur mit finances.read (der Tarif sagt etwas über die Person
    aus), sonst immer None."""

    login_status: Literal["active", "invited", "none"] = "none"
    roles: list[RoleRef] = Field(default_factory=list)
    tariff_id: uuid.UUID | None = None


class ParticipantBulkInvite(BaseModel):
    participant_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    # Rolle für alle Eingeladenen (ersetzt deren Rollen); None = Rollen unverändert
    role_id: uuid.UUID | None = None


class ParticipantBulkRoles(BaseModel):
    participant_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    role_ids: list[uuid.UUID] = Field(min_length=1, max_length=50)
    mode: Literal["add", "remove"]


class ParticipantBulkSkipped(BaseModel):
    participant_id: uuid.UUID
    # has_login, inactive, former, no_email, no_roles_left, not_allowed, protected, rate_limited, not_found, failed
    reason: str


class ParticipantBulkResult(BaseModel):
    done: list[uuid.UUID] = Field(default_factory=list)
    skipped: list[ParticipantBulkSkipped] = Field(default_factory=list)
