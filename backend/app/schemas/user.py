from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

class TenantRead(BaseModel):
    # Built via explicit keyword construction (tenant_service.py, auth_service.session())
    # in every call site - id is set from the tenant row's public_id there directly.
    id: uuid.UUID
    name: str
    profile_image_path: str | None = None
    profile_image_url: str | None = None
    public_slug: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    tag_config_json: dict[str, Any] = {}


class TenantMembershipWrite(BaseModel):
    tenant_id: uuid.UUID
    role_code: str
    is_active: bool = True


class TenantMembershipRead(BaseModel):
    # Built via explicit keyword construction (auth_service.session(), user_service.py) -
    # not from_attributes, since it's assembled from a CurrentUser/TenantMembership
    # dataclass, not an ORM row.
    tenant_id: uuid.UUID
    tenant_name: str
    tenant_profile_image_path: str | None = None
    tenant_profile_image_url: str | None = None
    role_code: str
    is_active: bool = True


class UserBase(BaseModel):
    first_name: str
    last_name: str
    display_name: str
    email: str
    preferred_language: str = "de"
    is_active: bool = True
    external_identity_json: dict[str, Any] = Field(default_factory=dict)
    default_tenant_id: uuid.UUID | None = None


class UserCreate(UserBase):
    password: str = Field(min_length=12)
    memberships: list[TenantMembershipWrite] = Field(default_factory=list)
    login_enabled: bool = True


class UserUpdate(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    display_name: str | None = None
    email: str | None = None
    preferred_language: str | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=12)
    external_identity_json: dict[str, Any] | None = None
    default_tenant_id: uuid.UUID | None = None
    memberships: list[TenantMembershipWrite] | None = None
    login_enabled: bool | None = None


class UserSelfUpdate(BaseModel):
    preferred_language: str | None = None
    default_tenant_id: uuid.UUID | None = None
    protocol_accordion_enabled: bool | None = None


class UserPasswordChange(BaseModel):
    """Self-service password change while logged in - requires the current password as
    confirmation. There is deliberately no "forgot password" email flow (no mail
    infrastructure exists in this project); that stays out of scope here."""

    current_password: str
    new_password: str = Field(min_length=12)


class UserRead(UserBase):
    # Built via explicit keyword construction in user_service.py (memberships are a
    # separately-queried list, not a plain ORM relationship) - id is set from the row's
    # public_id there directly.
    id: uuid.UUID
    memberships: list[TenantMembershipRead] = Field(default_factory=list)
    login_enabled: bool = True
    is_participant_account: bool = False
    created_at: datetime
    updated_at: datetime


class LoginRequest(BaseModel):
    email: str
    password: str
    tenant_id: uuid.UUID | None = None


class TenantByDomainRead(BaseModel):
    tenant_id: uuid.UUID
    tenant_name: str
    profile_image_url: str | None = None


class SessionUserRead(BaseModel):
    id: uuid.UUID
    first_name: str
    last_name: str
    display_name: str
    email: str
    preferred_language: str
    protocol_accordion_enabled: bool = True
    default_tenant_id: uuid.UUID | None = None


class SessionRead(BaseModel):
    authenticated: bool
    user: SessionUserRead | None = None
    current_tenant: TenantRead | None = None
    current_role: str | None = None
    available_tenants: list[TenantMembershipRead] = Field(default_factory=list)
    bridge_redirect_url: str | None = None


class TenantUpdate(BaseModel):
    name: str | None = None
    public_slug: str | None = Field(default=None, pattern=r"^[a-z0-9-]+$")


class TenantDomainCreate(BaseModel):
    purpose: str = Field(pattern=r"^(app|abgabebox)$")
    domain: str = Field(min_length=1, max_length=253)


class TenantDomainRead(BaseModel):
    # Built via explicit keyword construction (tenants.py's own domain-listing helper) -
    # not from_attributes, since challenge_record_name/target_host aren't ORM columns.
    id: uuid.UUID
    purpose: str
    domain: str
    status: str
    verification_token: str
    challenge_record_name: str
    target_host: str | None = None
    verified_at: datetime | None = None
    is_healthy: bool = True
    last_checked_at: datetime | None = None

    model_config = {"from_attributes": True}
