from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class TenantRead(BaseModel):
    id: int
    name: str
    profile_image_path: str | None = None
    profile_image_url: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class TenantMembershipWrite(BaseModel):
    tenant_id: int
    role_code: str
    is_active: bool = True


class TenantMembershipRead(BaseModel):
    tenant_id: int
    tenant_name: str
    tenant_profile_image_path: str | None = None
    role_code: str
    is_active: bool = True


class UserBase(BaseModel):
    first_name: str
    last_name: str
    display_name: str
    email: str
    preferred_language: str = "de"
    is_active: bool = True
    oidc_subject: str | None = None
    oidc_issuer: str | None = None
    oidc_email: str | None = None
    external_identity_json: dict[str, Any] = Field(default_factory=dict)
    default_tenant_id: int | None = None


class UserCreate(UserBase):
    password: str = Field(min_length=8)
    memberships: list[TenantMembershipWrite] = Field(default_factory=list)
    is_superadmin: bool = False
    login_enabled: bool = True


class UserUpdate(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    display_name: str | None = None
    email: str | None = None
    preferred_language: str | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8)
    oidc_subject: str | None = None
    oidc_issuer: str | None = None
    oidc_email: str | None = None
    external_identity_json: dict[str, Any] | None = None
    default_tenant_id: int | None = None
    memberships: list[TenantMembershipWrite] | None = None
    is_superadmin: bool | None = None
    login_enabled: bool | None = None


class UserSelfUpdate(BaseModel):
    preferred_language: str | None = None
    default_tenant_id: int | None = None


class UserMergeRequest(BaseModel):
    source_user_id: int
    target_user_id: int


class UserRead(UserBase):
    id: int
    memberships: list[TenantMembershipRead] = Field(default_factory=list)
    is_superadmin: bool = False
    login_enabled: bool = True
    is_participant_account: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class LoginRequest(BaseModel):
    email: str
    password: str
    tenant_id: int | None = None


class SessionUserRead(BaseModel):
    id: int
    first_name: str
    last_name: str
    display_name: str
    email: str
    preferred_language: str
    is_superadmin: bool


class SessionRead(BaseModel):
    authenticated: bool
    user: SessionUserRead | None = None
    current_tenant: TenantRead | None = None
    current_role: str | None = None
    available_tenants: list[TenantMembershipRead] = Field(default_factory=list)


class TenantCreate(BaseModel):
    name: str


class TenantUpdate(BaseModel):
    name: str | None = None
