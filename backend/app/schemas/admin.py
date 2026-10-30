from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.base import PublicIdModel
from app.schemas.mfa import MfaPendingLoginRead
from app.schemas.role import RoleRef
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
    # Optional seit dem neuen "Neuer Mandant"-Dialog: Slug, Plan und Abrechnung koennen direkt
    # beim Anlegen gesetzt werden (sonst wie bisher spaeter in den Mandant-Einstellungen).
    public_slug: str | None = Field(default=None, pattern=r"^[a-z0-9-]+$")
    plan_code: str | None = None
    billing_cycle: Literal["monthly", "yearly"] = "monthly"


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
    # Nach Downgrade nur noch lesend (tenant_feature.access = 'read_only')
    read_only_features: list[str] = []
    # Voll gebuchte Features, die nicht aus dem Plan kommen (Zusatzmodule, Bestandsschutz)
    addon_features: list[str] = []
    plan_code: str | None = None
    plan_name: str | None = None
    billing_cycle: Literal["monthly", "yearly"] = "monthly"
    user_limit_override: int | None = None
    # override ?? plan.included_user_limit - None bedeutet "kein Limit". Durchgesetzt beim
    # Aktivieren von Logins (user_limit_service).
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
    assigned_storage_packages: list[AdminTenantStoragePackageRead] = []
    discount_percent: float = 0
    billing_note: str | None = None
    # Abo-Start für die Forderungen im Cashflow (0127_cashflow). None = Erstellungsdatum.
    billing_start_date: date | None = None
    # Vertragsende für das Offboarding (0146); None = unbefristet
    contract_ends_on: date | None = None
    show_on_website: bool = False


class AdminTenantWebsiteListingUpdate(BaseModel):
    show_on_website: bool


class AdminFeatureRead(BaseModel):
    code: str
    name: str
    description: str | None = None
    # Rappen, nicht Franken. None = nur gebuendelt ueber einen Plan verfuegbar, nie einzeln
    # zubuchbar (z.B. 'finance' heute).
    standalone_price_monthly_rp: int | None = None


class AdminFeatureUpdate(BaseModel):
    # Full-Replace wie bei AdminTenantSubscriptionUpdate - der Code selbst (PK) bleibt fest,
    # alles andere wird komplett ersetzt.
    name: str
    description: str | None = None
    standalone_price_monthly_rp: int | None = Field(default=None, ge=0)


class AdminTenantFeaturesUpdate(BaseModel):
    # Full-Replace wie bei AdminTenantSubscriptionUpdate: der gesamte gebuchte Featureumfang,
    # kein Teil-Patch.
    enabled_codes: list[str]
    # Features im Zustand «nur lesen» (Daten lesbar, Änderungen gesperrt); ein Code in beiden
    # Listen gilt als voll gebucht.
    read_only_codes: list[str] = []


class AdminPlanRead(BaseModel):
    code: str
    name: str
    price_monthly_rp: int | None = None
    price_yearly_rp: int | None = None
    included_user_limit: int | None = None
    included_storage_bytes: int | None = None
    sort_order: int = 0
    feature_codes: list[str] = []
    description: str | None = None
    is_bookable: bool = True
    is_featured: bool = False
    # Priorität bei Überlast: 0 niedrig, 1 normal, 2 hoch (app/core/db_admission.py).
    load_priority: int = 1
    # Anzahl Mandanten mit diesem Plan (Karten auf der Preisseite, Filter der Mandantenliste).
    tenant_count: int = 0


class AdminPlanWrite(BaseModel):
    # Full-Replace, auch fuers Anlegen (PUT /api/admin/plans/{code}, Code kommt aus dem Pfad,
    # nicht aus dem Body - analog zu AdminTenantSubscriptionUpdate).
    name: str
    price_monthly_rp: int | None = Field(default=None, ge=0)
    price_yearly_rp: int | None = Field(default=None, ge=0)
    included_user_limit: int | None = Field(default=None, ge=0)
    included_storage_bytes: int | None = Field(default=None, ge=0)
    sort_order: int = 0
    feature_codes: list[str] = []
    description: str | None = None
    is_bookable: bool = True
    # "Beliebteste Wahl" auf der oeffentlichen Website; setzt beim Speichern alle anderen zurueck.
    is_featured: bool = False
    # Wer bei Überlast zuerst die Überlast-Seite sieht: 0 niedrig, 1 normal, 2 hoch (nie vorab).
    load_priority: int = Field(default=1, ge=0, le=2)
    # Nur bei POST /api/admin/plans ausgewertet: gewuenschter Code. Leer = aus dem Namen erzeugt.
    code: str | None = Field(default=None, pattern=r"^[a-z0-9_]+$")


class AdminStoragePackageRead(BaseModel):
    code: str
    name: str
    bytes: int
    price_monthly_rp: int | None = None
    price_yearly_rp: int | None = None
    sort_order: int = 0
    is_bookable: bool = True
    # Anzahl Mandanten, denen das Paket zugewiesen ist.
    tenant_count: int = 0


class AdminStoragePackageWrite(BaseModel):
    # Full-Replace wie bei AdminPlanWrite - der Code (PK) kommt aus dem Pfad.
    name: str
    bytes: int = Field(ge=0)
    price_monthly_rp: int | None = Field(default=None, ge=0)
    price_yearly_rp: int | None = Field(default=None, ge=0)
    sort_order: int = 0
    # False = kann nicht mehr neu zugebucht werden, bestehende Zuweisungen bleiben.
    is_bookable: bool = True


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
    # Prozent mit bis zu 4 Nachkommastellen (0161); das Adminportal rechnet einen eingegebenen
    # Preis in Prozent um.
    discount_percent: Decimal = Field(default=Decimal(0), ge=0, le=100, max_digits=7, decimal_places=4)
    billing_note: str | None = None
    # Full-Replace wie die übrigen Felder: None = Erstellungsdatum des Mandanten.
    billing_start_date: date | None = None
    contract_ends_on: date | None = None


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


class TenantCloneRequest(BaseModel):
    new_name: str
    mode: Literal["structure", "full"] = "structure"


class TenantExportRequest(BaseModel):
    scope: Literal["structure", "structure_lists", "full", "full_abgabebox"] = "structure"
    # Passwort-Hashes, MFA-Secrets und Link-Tokens nur auf ausdrücklichen Wunsch (Umzug, bei dem
    # alle Logins und Links weiter gelten sollen). Datenschutz-Audit Paket 6.
    include_credentials: bool = False
    # Optional: ohne Passwort wird mit dem Server-Schlüssel verschlüsselt (nur auf diesem Server
    # importierbar, app/services/export_crypto.py). Im Body, nie in der URL.
    password: str | None = Field(default=None, max_length=1024)


class TenantImportResult(BaseModel):
    tenant: AdminTenantRead
    warnings: list[str] = []


class AdminTenantUserRead(BaseModel):
    user_id: uuid.UUID
    email: str | None
    display_name: str
    roles: list[RoleRef] = Field(default_factory=list)
    login_enabled: bool
    is_active: bool


class AdminTenantUserGrant(BaseModel):
    # Plattform-Admin setzt genau eine Standardrolle (ersetzt alle Rollen des Kontos), z. B. im
    # Notfall "Administrator" - eigene Rollen verwaltet der Mandant selbst.
    role_code: Literal["admin", "writer", "kassier", "reader"]


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


JobState = Literal["ok", "running", "failing", "overdue", "never_run"]


class JobStatusRead(BaseModel):
    name: str
    # False = Job meldet sich, steht aber nicht in job_registry.py (z. B. neuer Host-Cronjob).
    registered: bool
    kind: str | None = None
    service: str | None = None
    category: str | None = None
    interval_seconds: int | None = None
    max_silence_seconds: int | None = None
    state: JobState
    last_status: str | None = None
    last_started_at: datetime | None = None
    last_finished_at: datetime | None = None
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    last_heartbeat_at: datetime | None = None
    last_duration_ms: int | None = None
    last_error: str | None = None
    consecutive_failures: int = 0
    run_count: int = 0
    failure_count: int = 0


class JobStatusOverview(BaseModel):
    items: list[JobStatusRead]
    generated_at: datetime


class JobRunRead(BaseModel):
    id: int
    status: str
    started_at: datetime
    finished_at: datetime
    duration_ms: int
    error: str | None = None


class JobRunPage(BaseModel):
    items: list[JobRunRead]
    total: int

HealthStatus = Literal["ok", "warning", "critical", "unknown"]
ProblemSeverity = Literal["warning", "critical"]


class ContainerStatusRead(BaseModel):
    name: str
    service: str
    container_id: str
    state: str
    health: str | None = None
    health_output: str | None = None
    restart_count: int = 0
    started_at: datetime | None = None
    exit_code: int | None = None
    oom_killed: bool = False
    image: str | None = None
    version: str | None = None
    cpu_percent: float | None = None
    memory_bytes: int | None = None
    memory_limit_bytes: int | None = None
    status: HealthStatus
    # Strukturierte Gründe für status != ok, z. B. "unhealthy", "not_running", "memory_high".
    reasons: list[str] = Field(default_factory=list)


class HealthCheckRead(BaseModel):
    key: str
    status: HealthStatus
    # Werte für die übersetzten Detailtexte im Frontend (admin.system.checks.<key>.detail).
    params: dict[str, str | int | float | None] = Field(default_factory=dict)
    error: str | None = None


class SystemHealthSnapshot(BaseModel):
    collected_at: datetime
    docker_configured: bool
    docker_available: bool
    docker_error: str | None = None
    compose_project: str | None = None
    containers: list[ContainerStatusRead] = Field(default_factory=list)
    checks: list[HealthCheckRead] = Field(default_factory=list)


class SystemProblemRead(BaseModel):
    key: str
    source: str
    subject: str
    reason: str
    severity: ProblemSeverity
    title: str
    message: str
    first_seen_at: datetime | None = None


class SystemHealthEventRead(BaseModel):
    id: int
    kind: str
    subject: str
    reason: str | None = None
    severity: str
    title: str
    message: str
    created_at: datetime


class OverloadTenantRead(BaseModel):
    """Abweisungen wegen Überlast je Mandant (overload_rejection, letzte OVERLOAD_HISTORY_DAYS)."""

    tenant_id: str | None = None
    tenant_name: str | None = None
    plan_name: str | None = None
    load_priority: int
    rejected: int
    users: int
    first_at: datetime
    last_at: datetime


class SystemStatusRead(BaseModel):
    snapshot: SystemHealthSnapshot | None = None
    stale: bool
    problems: list[SystemProblemRead]
    events: list[SystemHealthEventRead]
    overload: list[OverloadTenantRead] = []


class NotificationSettingsRead(BaseModel):
    ntfy_enabled: bool
    ntfy_server_url: str | None = None
    ntfy_topic: str | None = None
    # Das Token selbst verlässt das Backend nie wieder - nur ob eins gesetzt ist.
    ntfy_token_set: bool
    admin_url: str | None = None
    reminder_hours: int
    status_token: str | None = None
    # Fertige URL für den HTTP-Monitor in Uptime Kuma (ohne bekannte Domain nur der Pfad).
    status_url: str | None = None
    last_sent_at: datetime | None = None
    last_send_error: str | None = None
    last_send_error_at: datetime | None = None


class NotificationSettingsWrite(BaseModel):
    ntfy_enabled: bool
    ntfy_server_url: str | None = Field(default=None, max_length=500)
    ntfy_topic: str | None = Field(default=None, max_length=64)
    # None = unverändert lassen, "" = entfernen, sonst neues Token.
    ntfy_token: str | None = Field(default=None, max_length=500)
    admin_url: str | None = Field(default=None, max_length=500)
    reminder_hours: int = Field(default=6, ge=0, le=168)


class NotificationTestResult(BaseModel):
    ok: bool
    error: str | None = None

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


class AuditLogEntryRead(BaseModel):
    """Eintrag im Audit-Log für /admin/audit (Datenschutz-Audit PRIV-013)."""

    id: int
    created_at: datetime
    action: str
    outcome: str
    tenant_id: uuid.UUID | None = None
    tenant_name: str | None = None
    actor_email: str | None = None
    actor_name: str | None = None
    ip_hash: str | None = None
    entity_type: str | None = None
    entity_id: int | None = None
    details: dict = {}


class AuditLogPage(BaseModel):
    items: list[AuditLogEntryRead]
    total: int
