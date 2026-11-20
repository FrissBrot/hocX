"""Step-up (SEC-AUTH-010) und Sitzungsverwaltung (SEC-AUTH-011)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

StepUpMethod = Literal["totp", "passkey", "password"]


class StepUpOptionsRead(BaseModel):
    methods: list[StepUpMethod]
    auth_time: datetime | None = None


class StepUpRequest(BaseModel):
    method: StepUpMethod
    code: str | None = Field(default=None, max_length=16)
    password: str | None = Field(default=None, max_length=1024)
    flow_token: str | None = Field(default=None, max_length=128)
    credential: dict[str, Any] | None = None


class StepUpRead(BaseModel):
    auth_time: datetime


class SessionDeviceRead(BaseModel):
    """Eine aktive Session in «Angemeldete Geräte» - ohne IP, nur grobe Merkmale."""
    id: uuid.UUID
    current: bool
    user_agent_family: str | None = None
    host: str | None = None
    created_at: datetime
    last_seen_at: datetime
    mfa: bool
    # Session auf einer Mandanten-Domain, die über die Domain-Bridge aus einer anderen entstand
    via_bridge: bool = False


class SessionListRead(BaseModel):
    sessions: list[SessionDeviceRead]
    # Sessions von vor dem Update (ohne Register) lassen sich nur gesamthaft beenden
    legacy_session: bool = False


class EmailChallengeResendRequest(BaseModel):
    ticket: str = Field(min_length=1, max_length=128)


class KnownDeviceRead(BaseModel):
    """Bekanntes Gerät (von Konto- und Quellsperren ausgenommen), ohne Geräte-ID."""
    id: uuid.UUID
    user_agent_family: str | None = None
    created_at: datetime
    last_seen_at: datetime
    current: bool = False
