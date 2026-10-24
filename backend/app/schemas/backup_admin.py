"""Schemas der Backup-Verwaltung im Plattform-Admin (/api/admin/backups, /api/admin/restores).
Nie Secrets: Schlüssel, Passphrasen und Zugangsdaten existieren nur beim backup-worker."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

Severity = Literal["warning", "critical"]


class BackupProblemRead(BaseModel):
    code: str
    severity: Severity
    params: dict[str, Any] = Field(default_factory=dict)


class BackupSetRead(BaseModel):
    id: uuid.UUID
    archive_name: str
    state: str
    trigger: str
    protected: bool
    protected_reason: str | None
    snapshot_at: datetime
    finished_at: datetime | None
    app_version: str | None
    alembic_revision: str | None
    generation: int | None
    profile_name: str | None
    profile_provider: str | None
    db_dump_bytes: int | None
    object_count: int
    object_bytes: int
    new_object_count: int
    new_object_bytes: int
    deduplicated_bytes: int | None
    duration_seconds: int | None
    verify_state: str
    verified_at: datetime | None
    restore_test_state: str
    restore_tested_at: datetime | None
    warnings: list[dict[str, Any]]
    tenant_count: int
    reconstructed: bool


class BackupTenantRead(BaseModel):
    id: int
    public_id: str | None = None
    name: str
    users: int = 0
    objects: int = 0
    bytes: int = 0


class BackupJobRead(BaseModel):
    id: uuid.UUID
    kind: str
    trigger: str
    state: str
    requested_by_email: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    heartbeat_at: datetime | None
    worker_active: bool
    attempt: int
    cancel_requested: bool
    progress: dict[str, Any]
    error_code: str | None
    error_message: str | None
    warning_count: int
    duration_seconds: int | None
    backup_set: BackupSetRead | None = None


class BackupEventRead(BaseModel):
    id: int
    created_at: datetime
    level: str
    kind: str
    actor_email: str | None
    message: str | None
    details: dict[str, Any]


class BackupJobDetailRead(BackupJobRead):
    result: dict[str, Any] | None
    events: list[BackupEventRead]
    tenants: list[BackupTenantRead] = Field(default_factory=list)


class BackupJobPage(BaseModel):
    items: list[BackupJobRead]
    total: int
    offset: int
    limit: int


class RepositoryStatusRead(BaseModel):
    ok: bool | None = None
    checked_at: str | None = None
    last_ok_at: str | None = None
    error_code: str | None = None
    error: str | None = None
    repository_id: str | None = None
    encryption: str | None = None
    borg_version: str | None = None
    stored_bytes: int | None = None
    original_bytes: int | None = None
    deduplicated_bytes: int | None = None
    quota_bytes: int | None = None
    used_percent: float | None = None
    staging_free_bytes: int | None = None
    staging_total_bytes: int | None = None
    last_gc_at: str | None = None
    last_verify_at: str | None = None
    last_verify_ok: bool | None = None
    last_restore_test_at: str | None = None
    last_restore_test_ok: bool | None = None


class RestoreJobRead(BaseModel):
    id: uuid.UUID
    kind: str
    state: str
    archive_name: str
    backup_set_id: uuid.UUID | None
    options: dict[str, Any]
    plan: dict[str, Any]
    requested_by_email: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    heartbeat_at: datetime | None
    worker_active: bool
    progress: dict[str, Any]
    error_code: str | None
    error_message: str | None
    result: dict[str, Any] | None
    cancel_requested: bool
    events: list[BackupEventRead] = Field(default_factory=list)


class BackupStatusRead(BaseModel):
    enabled: bool
    overall: Literal["ok", "warning", "critical", "disabled"]
    problems: list[BackupProblemRead]
    last_success: BackupSetRead | None
    last_failure: BackupJobRead | None
    next_backup_at: datetime | None
    restore_point_count: int
    protected_count: int
    latest_object_bytes: int | None
    latest_db_bytes: int | None
    repository: RepositoryStatusRead
    last_verified_at: datetime | None
    last_verified_archive: str | None
    last_restore_test_at: datetime | None
    last_restore_test_archive: str | None
    current_job: BackupJobRead | None
    current_restore: RestoreJobRead | None
    worker_heartbeat_at: datetime | None
    worker_alive: bool


class BackupSettingsRead(BaseModel):
    schedule_enabled: bool
    interval_hours: int
    schedule_offset_minutes: int
    keep_within_days: int
    keep_daily: int
    keep_weekly: int
    keep_monthly: int
    verify_interval_hours: int
    verify_sample_objects: int
    restore_test_interval_days: int
    success_notification: Literal["off", "daily", "each"]
    worker_config: dict[str, Any]
    repository: RepositoryStatusRead
    ntfy_configured: bool
    updated_at: datetime
    updated_by_email: str | None


class BackupSettingsUpdate(BaseModel):
    schedule_enabled: bool
    interval_hours: int = Field(ge=1, le=168)
    schedule_offset_minutes: int = Field(ge=0, le=1439)
    keep_within_days: int = Field(ge=0, le=3650)
    keep_daily: int = Field(ge=0, le=3650)
    keep_weekly: int = Field(ge=0, le=520)
    keep_monthly: int = Field(ge=0, le=240)
    verify_interval_hours: int = Field(ge=1, le=8760)
    verify_sample_objects: int = Field(ge=0, le=100000)
    restore_test_interval_days: int = Field(ge=1, le=365)
    success_notification: Literal["off", "daily", "each"]

    @field_validator("keep_monthly")
    @classmethod
    def _some_retention(cls, value: int, info) -> int:
        data = info.data
        if value + data.get("keep_within_days", 0) + data.get("keep_daily", 0) + data.get("keep_weekly", 0) == 0:
            raise ValueError("Mindestens eine Aufbewahrungsregel muss Sicherungen behalten")
        return value


class BackupCreate(BaseModel):
    idempotency_key: str | None = Field(default=None, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")
    protected: bool = False
    reason: str | None = Field(default=None, max_length=300)


class VerifyCreate(BaseModel):
    deep: bool = False
    idempotency_key: str | None = Field(default=None, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")


class RestorePreviewRequest(BaseModel):
    backup_set_id: uuid.UUID
    kind: Literal["full", "tenant_copy"]
    target_profile_id: uuid.UUID | None = None
    source_tenant_id: int | None = Field(default=None, ge=1)
    new_name: str | None = Field(default=None, min_length=1, max_length=200)


class RestorePreviewRead(BaseModel):
    kind: str
    backup_set: BackupSetRead
    schema_state: str
    schema_revision: str | None
    schema_head: str | None
    target_profile_name: str | None = None
    target_profile_provider: str | None = None
    tenant: BackupTenantRead | None = None
    new_name: str | None = None
    name_conflict: bool = False
    steps: list[str]
    risks: list[str]
    blockers: list[str]
    confirmation_phrase: str
    requires_totp: bool = True
    estimated_bytes: int


class RestoreCreate(RestorePreviewRequest):
    confirmation: str = Field(min_length=1, max_length=200)
    totp_code: str = Field(min_length=6, max_length=10, pattern=r"^[0-9 ]+$")
    skip_rescue_backup: bool = False
    skip_rescue_reason: str | None = Field(default=None, max_length=500)
    # Löschungen nach dem Sicherungspunkt erneut anwenden (Löschjournal, PRIV-010); aus nur mit Begründung.
    replay_erasures: bool = True
    replay_erasures_reason: str | None = Field(default=None, max_length=500)
    idempotency_key: str | None = Field(default=None, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")
