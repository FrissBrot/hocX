from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.base import PublicIdModel
from app.schemas.user import UserRead


class AdminLoginRequest(BaseModel):
    email: str
    password: str


class AdminSelfRead(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str
    role: Literal["owner", "support"] = "owner"


class AdminSessionRead(BaseModel):
    authenticated: bool
    admin: AdminSelfRead | None = None


class PlatformAdminCreate(BaseModel):
    email: str
    display_name: str
    password: str = Field(min_length=12)
    is_active: bool = True
    role: Literal["owner", "support"] = "owner"


class PlatformAdminUpdate(BaseModel):
    display_name: str | None = None
    password: str | None = Field(default=None, min_length=12)
    is_active: bool | None = None
    role: Literal["owner", "support"] | None = None


class PlatformAdminRead(PublicIdModel):
    id: uuid.UUID
    email: str
    display_name: str
    is_active: bool
    role: Literal["owner", "support"]
    created_at: datetime
    updated_at: datetime


class AdminTenantCreate(BaseModel):
    name: str


class AdminTenantRead(BaseModel):
    # Built via explicit keyword construction (AdminTenantService - participant_count/
    # user_count are aggregate query results, not plain ORM attributes).
    id: uuid.UUID
    name: str
    profile_image_path: str | None = None
    profile_image_url: str | None = None
    public_slug: str | None = None
    participant_count: int = 0
    user_count: int = 0
    created_at: datetime


class AdminTenantPage(BaseModel):
    items: list[AdminTenantRead]
    total: int


class AdminDomainRead(BaseModel):
    # Built via explicit keyword construction (AdminDomainService - tenant_name is a join
    # column, not a plain ORM attribute).
    id: uuid.UUID
    tenant_id: uuid.UUID
    tenant_name: str
    purpose: str
    domain: str
    status: str
    is_healthy: bool
    last_checked_at: datetime | None = None
    verified_at: datetime | None = None
    created_at: datetime


class AdminDomainPage(BaseModel):
    items: list[AdminDomainRead]
    total: int


class AdminUserPage(BaseModel):
    items: list[UserRead]
    total: int


class AdminUserMergeRequest(BaseModel):
    source_user_id: uuid.UUID
    target_user_id: uuid.UUID


class TenantCloneRequest(BaseModel):
    new_name: str
    mode: Literal["structure", "full"] = "structure"


class TenantImportResult(BaseModel):
    tenant: AdminTenantRead
    warnings: list[str] = []


class AdminTenantUserRead(BaseModel):
    user_id: uuid.UUID
    email: str
    display_name: str
    role_code: str
    login_enabled: bool
    is_active: bool


class AdminTenantUserGrant(BaseModel):
    role_code: str


class SystemErrorLogRead(BaseModel):
    # Built via explicit keyword construction (AdminErrorLogService - tenant_name is a
    # join column, not a plain ORM attribute).
    id: uuid.UUID
    source: str
    tenant_id: uuid.UUID | None = None
    tenant_name: str | None = None
    actor_email: str | None = None
    request_method: str | None = None
    request_path: str | None = None
    status_code: int | None = None
    error_type: str
    error_message: str
    traceback: str | None = None
    created_at: datetime


class SystemErrorLogPage(BaseModel):
    items: list[SystemErrorLogRead]
    total: int


class SystemErrorLogFilterOptions(BaseModel):
    error_types: list[str]
    sources: list[str]


TenantCleanupCategory = Literal[
    "protocols", "list_entries", "lists_full", "events", "todos", "participants", "documents"
]


class TenantCleanupCounts(BaseModel):
    protocols: int = 0
    list_entries: int = 0
    lists_full: int = 0
    events: int = 0
    todos: int = 0
    participants: int = 0
    documents: int = 0


class TenantCleanupRequest(BaseModel):
    categories: list[TenantCleanupCategory]
    confirm_name: str
