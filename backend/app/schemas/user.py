from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class UserBase(BaseModel):
    tenant_id: int = 1
    name: str
    email: str
    is_active: bool = True
    oidc_subject: str | None = None
    oidc_issuer: str | None = None
    oidc_email: str | None = None
    external_identity_json: dict[str, Any] = Field(default_factory=dict)


class UserCreate(UserBase):
    pass


class UserUpdate(BaseModel):
    name: str | None = None
    email: str | None = None
    is_active: bool | None = None
    oidc_subject: str | None = None
    oidc_issuer: str | None = None
    oidc_email: str | None = None
    external_identity_json: dict[str, Any] | None = None


class UserRead(UserBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
