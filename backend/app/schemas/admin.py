from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class AdminLoginRequest(BaseModel):
    email: str
    password: str


class AdminSelfRead(BaseModel):
    id: int
    email: str
    display_name: str


class AdminSessionRead(BaseModel):
    authenticated: bool
    admin: AdminSelfRead | None = None


class PlatformAdminCreate(BaseModel):
    email: str
    display_name: str
    password: str = Field(min_length=8)
    is_active: bool = True


class PlatformAdminUpdate(BaseModel):
    display_name: str | None = None
    password: str | None = Field(default=None, min_length=8)
    is_active: bool | None = None


class PlatformAdminRead(BaseModel):
    id: int
    email: str
    display_name: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AdminTenantCreate(BaseModel):
    name: str


class AdminTenantRead(BaseModel):
    id: int
    name: str
    profile_image_path: str | None = None
    profile_image_url: str | None = None
    public_slug: str | None = None
    participant_count: int = 0
    user_count: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}


class AdminUserMergeRequest(BaseModel):
    source_user_id: int
    target_user_id: int
