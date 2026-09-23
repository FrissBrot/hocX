from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

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
    enabled_features: list[str] = []


class TenantSubscriptionFeatureRead(BaseModel):
    code: str
    name: str
    standalone_price_monthly_rp: int | None = None
    # Teil des aktuellen Plans (kostet nicht zusaetzlich) vs. einzeln zugebucht.
    included_in_plan: bool = False


class TenantSubscriptionRead(BaseModel):
    """Fuer den Abo-Abschnitt in TenantSettingsManager (Phase 4) - eigenes Schema statt einer
    Erweiterung von TenantRead, weil das hier eine bewusst separate, seltener aufgerufene
    Abfrage ist (Plan-Join, Nutzerzahl, Speicherverbrauch), nicht Teil von jedem Session-Fetch."""

    plan_code: str | None = None
    plan_name: str | None = None
    billing_cycle: Literal["monthly", "yearly"] = "monthly"
    plan_price_monthly_rp: int | None = None
    plan_price_yearly_rp: int | None = None
    included_user_limit: int | None = None
    included_storage_bytes: int | None = None
    user_limit_override: int | None = None
    effective_user_limit: int | None = None
    user_count: int = 0
    storage_used_bytes: int = 0
    storage_quota_bytes: int | None = None
    features: list[TenantSubscriptionFeatureRead] = []
    # None, wenn der Plan selbst keinen Preis hat (z.B. 'legacy') und keine zusaetzlichen
    # bepreisten Features gebucht sind - dann gibt es schlicht nichts zu beziffern.
    estimated_monthly_cost_rp: int | None = None
    estimated_yearly_cost_rp: int | None = None


class UserBase(BaseModel):
    first_name: str
    last_name: str
    display_name: str
    email: str
    preferred_language: str = "de"
    is_active: bool = True
    external_identity_json: dict[str, Any] = Field(default_factory=dict)


class UserCreate(UserBase):
    password: str = Field(min_length=12)
    role_code: str = "reader"
    # Only the platform-admin panel picks the tenant; a tenant admin always creates users in
    # their own tenant (a differing tenant_id is rejected there).
    tenant_id: uuid.UUID | None = None
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
    role_code: str | None = None
    login_enabled: bool | None = None


class UserSelfUpdate(BaseModel):
    preferred_language: str | None = None
    protocol_accordion_enabled: bool | None = None


class UserPasswordChange(BaseModel):
    """Self-service password change while logged in - requires the current password as
    confirmation. There is deliberately no "forgot password" email flow (no mail
    infrastructure exists in this project); that stays out of scope here."""

    current_password: str
    new_password: str = Field(min_length=12)


class UserRead(UserBase):
    # Built via explicit keyword construction in user_service.py - id and tenant_id are set
    # from the rows' public_id there directly.
    id: uuid.UUID
    tenant_id: uuid.UUID
    tenant_name: str
    role_code: str
    login_enabled: bool = True
    is_participant_account: bool = False
    created_at: datetime
    updated_at: datetime


class LoginRequest(BaseModel):
    email: str
    password: str


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


class SessionRead(BaseModel):
    authenticated: bool
    user: SessionUserRead | None = None
    current_tenant: TenantRead | None = None
    current_role: str | None = None
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
