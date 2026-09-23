from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.base import PublicIdModel
from app.schemas.mfa import MfaPendingLoginRead
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
    # Mirrors LoginResponse.mfa (schemas/mfa.py) for the tenant-user login flow - set instead
    # of `admin` whenever password auth succeeded but MFA verification/enrollment is still
    # pending (audit finding, 2026-08-27). Same shape on purpose so the frontend's existing
    # tenant-login MFA-challenge UI can be reused for the admin panel with minimal changes.
    mfa: MfaPendingLoginRead | None = None


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


class AdminTenantStoragePackageRead(BaseModel):
    package_code: str
    name: str
    bytes: int
    quantity: int
    total_bytes: int


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
    storage_used_bytes: int = 0
    storage_quota_bytes: int | None = None
    enabled_features: list[str] = []
    plan_code: str | None = None
    plan_name: str | None = None
    billing_cycle: Literal["monthly", "yearly"] = "monthly"
    user_limit_override: int | None = None
    # override ?? plan.included_user_limit - None bedeutet "kein Limit". Rein informativ fuers
    # Adminportal (Phase-0-Entscheidung: erst Anzeige/Warnung, keine harte Sperre).
    effective_user_limit: int | None = None
    # Aufschluesselung des Speicherkontingents (0087_storage_packages): plan_storage_bytes ist
    # das Plan-Kontingent, package_storage_bytes die Summe der zugewiesenen Zusatzpakete
    # (bytes * quantity). storage_quota_bytes bleibt der tatsaechlich durchgesetzte Wert -
    # effective_storage_quota_bytes ist derselbe Wert, hier nur explizit benannt, damit die UI
    # nicht raten muss, ob "das enforcte Kontingent" gemeint ist. Weichen sie je auseinander,
    # war das ein Bug in recompute_effective_storage_quota().
    plan_storage_bytes: int | None = None
    package_storage_bytes: int = 0
    effective_storage_quota_bytes: int | None = None
    storage_quota_manual_override: bool = False
    assigned_storage_packages: list[AdminTenantStoragePackageRead] = []


class AdminTenantStorageQuotaUpdate(BaseModel):
    # None = manuellen Override entfernen, Kontingent wird wieder automatisch aus Plan +
    # Paketen berechnet (Feld ist bewusst ohne Default, damit ein Client es nicht aus
    # Versehen weglassen kann - anders als bei PATCH /tenants/{id} ist das hier der gesamte
    # Payload, nicht ein optionales Teilfeld eines groesseren Formulars).
    quota_mb: int | None = Field(ge=1)


class AdminFeatureRead(BaseModel):
    code: str
    name: str
    description: str | None = None
    # Rappen, nicht Franken. None = nur gebuendelt ueber einen Plan verfuegbar, nie einzeln
    # zubuchbar (z.B. 'finance' heute).
    standalone_price_monthly_rp: int | None = None


class AdminFeatureUpdate(BaseModel):
    # Full-Replace wie bei AdminTenantStorageQuotaUpdate - der Code selbst (PK) bleibt fest,
    # alles andere wird komplett ersetzt.
    name: str
    description: str | None = None
    standalone_price_monthly_rp: int | None = None


class AdminTenantFeaturesUpdate(BaseModel):
    # Full-Replace wie bei AdminTenantStorageQuotaUpdate: der gesamte gebuchte Featureumfang,
    # kein Teil-Patch.
    enabled_codes: list[str]


class AdminPlanRead(BaseModel):
    code: str
    name: str
    price_monthly_rp: int | None = None
    price_yearly_rp: int | None = None
    included_user_limit: int | None = None
    included_storage_bytes: int | None = None
    sort_order: int = 0
    feature_codes: list[str] = []


class AdminPlanWrite(BaseModel):
    # Full-Replace, auch fuers Anlegen (PUT /api/admin/plans/{code}, Code kommt aus dem Pfad,
    # nicht aus dem Body - analog zu AdminTenantStorageQuotaUpdate).
    name: str
    price_monthly_rp: int | None = None
    price_yearly_rp: int | None = None
    included_user_limit: int | None = None
    included_storage_bytes: int | None = None
    sort_order: int = 0
    feature_codes: list[str] = []


class AdminStoragePackageRead(BaseModel):
    code: str
    name: str
    bytes: int
    price_monthly_rp: int | None = None
    price_yearly_rp: int | None = None
    sort_order: int = 0


class AdminStoragePackageWrite(BaseModel):
    # Full-Replace wie bei AdminPlanWrite - der Code (PK) kommt aus dem Pfad.
    name: str
    bytes: int
    price_monthly_rp: int | None = None
    price_yearly_rp: int | None = None
    sort_order: int = 0


class AdminTenantStoragePackageItem(BaseModel):
    package_code: str
    quantity: int = Field(ge=1, default=1)


class AdminTenantStoragePackagesUpdate(BaseModel):
    # Full-Replace wie bei AdminTenantFeaturesUpdate: die gesamte Paketzuweisung des Mandanten,
    # kein Teil-Patch.
    items: list[AdminTenantStoragePackageItem] = []


class AdminTenantSubscriptionUpdate(BaseModel):
    plan_code: str | None = None
    billing_cycle: Literal["monthly", "yearly"] = "monthly"
    user_limit_override: int | None = None


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


UploadPipelineSource = Literal["protocol_image", "gallery_upload", "word_import", "submission_upload"]


class UploadPipelineFileRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    tenant_name: str
    original_name: str
    mime_type: str | None = None
    file_size_bytes: int | None = None
    source: UploadPipelineSource
    origin_tag: str
    scan_status: str
    created_at: datetime


class UploadPipelineStatusPage(BaseModel):
    items: list[UploadPipelineFileRead]
    total: int


class UploadPipelineSummaryEntry(BaseModel):
    source: UploadPipelineSource
    scan_status: str
    count: int


class AbgabeboxQuarantineEntry(BaseModel):
    tenant_id: uuid.UUID | None = None
    tenant_name: str | None = None
    assignment_id: int | None = None
    file_name: str
    age_seconds: int
    file_size_bytes: int


class UploadPipelineOverview(BaseModel):
    summary: list[UploadPipelineSummaryEntry]
    files: UploadPipelineStatusPage
    abgabebox_quarantine: list[AbgabeboxQuarantineEntry]


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
