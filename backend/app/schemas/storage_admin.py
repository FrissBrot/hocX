from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

Provider = Literal["garage_local", "aws_s3", "hetzner", "s3_compatible"]
DataLocation = Literal["ch", "eu_eea", "adequate", "third_country"]


class StorageProfileRead(BaseModel):
    """Nie mit Klartext-Zugangsdaten: Access Key nur maskiert, Secret gar nicht."""

    id: uuid.UUID
    name: str
    provider: str
    endpoint_url: str | None
    region: str | None
    bucket: str | None
    abgabebox_bucket: str | None
    prefix: str
    addressing_style: str
    access_key_masked: str | None
    has_secret_key: bool
    has_restricted_credentials: bool
    tls_verify: bool
    has_ca_bundle: bool
    is_enabled: bool
    is_builtin: bool
    is_active: bool
    in_use_by_migration: bool
    pinned_generations: list[int]
    config_version: int
    last_test_at: datetime | None
    last_test_ok: bool | None
    last_test_error: str | None
    # Datenstandort (Datenschutz-Audit E3)
    data_location: DataLocation | None = None
    transfer_basis: str | None = None
    location_confirmed_by: str | None = None
    location_confirmed_at: datetime | None = None
    server_side_encryption: bool = False
    created_at: datetime
    updated_at: datetime


class StorageProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    provider: Provider
    endpoint_url: str | None = Field(default=None, max_length=500)
    region: str | None = Field(default=None, max_length=100)
    bucket: str = Field(min_length=3, max_length=63)
    abgabebox_bucket: str | None = Field(default=None, max_length=63)
    prefix: str | None = Field(default=None, max_length=200)
    addressing_style: Literal["auto", "path", "virtual"] | None = None
    access_key: str = Field(min_length=1, max_length=256)
    secret_key: str = Field(min_length=1, max_length=512)
    restricted_access_key: str | None = Field(default=None, max_length=256)
    restricted_secret_key: str | None = Field(default=None, max_length=512)
    tls_verify: bool = True
    ca_bundle_pem: str | None = Field(default=None, max_length=20000)
    is_enabled: bool = True
    # Nur für s3_compatible frei wählbar, sonst aus Anbieter und Region abgeleitet. Drittland nur mit
    # transfer_basis und location_confirmed (Auslandübermittlung geprüft, Vereine informiert).
    data_location: DataLocation | None = None
    transfer_basis: str | None = Field(default=None, max_length=1000)
    location_confirmed: bool | None = None
    server_side_encryption: bool | None = None


class StorageProfileUpdate(BaseModel):
    """Nicht gesetzte Felder bleiben unverändert; leere Strings bei Zugangsdaten löschen sie."""

    name: str | None = Field(default=None, max_length=120)
    provider: Provider | None = None
    endpoint_url: str | None = Field(default=None, max_length=500)
    region: str | None = Field(default=None, max_length=100)
    bucket: str | None = Field(default=None, max_length=63)
    abgabebox_bucket: str | None = Field(default=None, max_length=63)
    prefix: str | None = Field(default=None, max_length=200)
    addressing_style: Literal["auto", "path", "virtual"] | None = None
    access_key: str | None = Field(default=None, max_length=256)
    secret_key: str | None = Field(default=None, max_length=512)
    restricted_access_key: str | None = Field(default=None, max_length=256)
    restricted_secret_key: str | None = Field(default=None, max_length=512)
    tls_verify: bool | None = None
    ca_bundle_pem: str | None = Field(default=None, max_length=20000)
    is_enabled: bool | None = None
    # Nur für s3_compatible frei wählbar, sonst aus Anbieter und Region abgeleitet. Drittland nur mit
    # transfer_basis und location_confirmed (Auslandübermittlung geprüft, Vereine informiert).
    data_location: DataLocation | None = None
    transfer_basis: str | None = Field(default=None, max_length=1000)
    location_confirmed: bool | None = None
    server_side_encryption: bool | None = None


class StorageConnectionTestRead(BaseModel):
    ok: bool
    main: dict[str, Any] | None = None
    abgabebox: dict[str, Any] | None = None
    error: str | None = None
    restricted_credentials: bool = False


class StorageGenerationRead(BaseModel):
    id: int
    profile_id: uuid.UUID
    profile_name: str
    generation: int
    status: str
    object_count: int | None
    total_bytes: int | None
    created_at: datetime
    activated_at: datetime | None
    deactivated_at: datetime | None
    retain_until: datetime | None
    purge_requested_by: str | None
    purged_at: datetime | None
    purge_error: str | None


class StorageMigrationEventRead(BaseModel):
    id: int
    created_at: datetime
    level: str
    kind: str
    actor_email: str | None
    from_state: str | None
    to_state: str | None
    message: str | None
    details: dict[str, Any]

    model_config = {"from_attributes": True}


class StorageMigrationRead(BaseModel):
    id: uuid.UUID
    kind: str
    state: str
    resume_state: str | None
    source_profile_name: str
    source_provider: str
    source_generation: int
    target_profile_name: str
    target_provider: str
    target_generation: int
    requested_by_email: str | None
    options: dict[str, Any]
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    phase_started_at: datetime | None
    heartbeat_at: datetime | None
    checkpoint_at: datetime | None
    worker_active: bool
    total_objects: int
    total_bytes: int
    copied_objects: int
    copied_bytes: int
    verified_objects: int
    failed_objects: int
    status_counts: dict[str, dict[str, int]] = Field(default_factory=dict)
    current_bps: int | None = None
    average_bps: int | None = None
    eta_seconds: int | None = None
    estimate: dict[str, Any] | None = None
    live_estimate: dict[str, Any] | None = None
    last_error: str | None
    attempt: int
    pause_requested: bool
    cancel_requested: bool
    cutover_confirmed_at: datetime | None
    cutover_committed_at: datetime | None
    needs_cutover_confirmation: bool = False
    reference_check: dict[str, Any] | None = None
    maintenance_window_id: uuid.UUID | None
    final_integrity_ok: bool = False
    events: list[StorageMigrationEventRead] = Field(default_factory=list)


class StorageMigrationCreate(BaseModel):
    target_profile_id: uuid.UUID
    options: dict[str, Any] = Field(default_factory=dict)
    # Ziel in einem Drittland: erneut bestätigen (Datenschutz-Audit E3)
    confirm_third_country: bool = False


class StorageMigrationObjectRead(BaseModel):
    namespace: str
    key: str
    expected_size: int | None
    status: str
    attempts: int
    last_error: str | None
    updated_at: datetime

    model_config = {"from_attributes": True}


class StorageOverviewRead(BaseModel):
    active_profile: StorageProfileRead
    active_generation: int
    write_fenced: bool
    fence_reason: str | None
    credentials_key_configured: bool
    local_s3: dict[str, Any]
    open_migration: StorageMigrationRead | None
    generations: list[StorageGenerationRead]
    profiles: list[StorageProfileRead]


class GenerationPurgeRequest(BaseModel):
    confirmation: str = Field(min_length=1, max_length=40)
