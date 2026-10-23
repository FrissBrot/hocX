"""ORM-Modelle für Objektspeicher (Migration 0113) und Wartungssystem (Migration 0114)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Identity, Integer, SmallInteger, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _now():
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))


class StorageProfile(Base):
    __tablename__ = "storage_profile"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("gen_random_uuid()"))
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    endpoint_url: Mapped[str | None] = mapped_column(Text)
    region: Mapped[str | None] = mapped_column(Text)
    bucket: Mapped[str | None] = mapped_column(Text)
    abgabebox_bucket: Mapped[str | None] = mapped_column(Text)
    prefix: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    addressing_style: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'auto'"))
    access_key_enc: Mapped[str | None] = mapped_column(Text)
    secret_key_enc: Mapped[str | None] = mapped_column(Text)
    restricted_access_key_enc: Mapped[str | None] = mapped_column(Text)
    restricted_secret_key_enc: Mapped[str | None] = mapped_column(Text)
    tls_verify: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    ca_bundle_pem: Mapped[str | None] = mapped_column(Text)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    config_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean)
    last_test_error: Mapped[str | None] = mapped_column(Text)
    created_by_email: Mapped[str | None] = mapped_column(Text)
    # Datenstandort (0147, Datenschutz-Audit E3): ch | eu_eea | adequate | third_country
    data_location: Mapped[str | None] = mapped_column(Text)
    transfer_basis: Mapped[str | None] = mapped_column(Text)
    location_confirmed_by: Mapped[str | None] = mapped_column(Text)
    location_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    server_side_encryption: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), default=False)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _now()


class StorageState(Base):
    __tablename__ = "storage_state"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    active_profile_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("storage_profile.id"), nullable=False)
    active_generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    write_fenced: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    fence_reason: Mapped[str | None] = mapped_column(Text)
    fence_token: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    fenced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    local_s3_requested_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Backup-Hold (Migration 0115): Copy-on-Write für Objekte der gehaltenen Generation.
    backup_hold_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    backup_hold_generation: Mapped[int | None] = mapped_column(BigInteger)
    backup_hold_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = _now()


class StorageGeneration(Base):
    __tablename__ = "storage_generation"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    profile_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("storage_profile.id"), nullable=False)
    generation: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    migration_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    object_count: Mapped[int | None] = mapped_column(BigInteger)
    total_bytes: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = _now()
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retain_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    purge_requested_by: Mapped[str | None] = mapped_column(Text)
    purge_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    purge_error: Mapped[str | None] = mapped_column(Text)


class StorageObject(Base):
    __tablename__ = "storage_object"

    namespace: Mapped[str] = mapped_column(Text, primary_key=True)
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    sha256: Mapped[str | None] = mapped_column(Text)
    content_type: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("1"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # Tombstone: Löschung committet, physisches Entfernen durch den Job storage_purge offen (S3-008).
    purge_pending: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _now()


class StorageChangeOutbox(Base):
    __tablename__ = "storage_change_outbox"

    seq: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    namespace: Mapped[str] = mapped_column(Text, nullable=False)
    key: Mapped[str] = mapped_column(Text, nullable=False)
    op: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    sha256: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = _now()


class StorageMigration(Base):
    __tablename__ = "storage_migration"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    resume_state: Mapped[str | None] = mapped_column(Text)
    source_profile_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("storage_profile.id"), nullable=False)
    source_generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_config_version: Mapped[int] = mapped_column(Integer, nullable=False)
    target_profile_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("storage_profile.id"), nullable=False)
    target_generation: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    target_config_version: Mapped[int] = mapped_column(Integer, nullable=False)
    requested_by_email: Mapped[str | None] = mapped_column(Text)
    options: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = _now()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = _now()
    phase_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_owner: Mapped[str | None] = mapped_column(Text)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fencing_token: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    checkpoint_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    checkpoint: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    snapshot_outbox_seq: Mapped[int | None] = mapped_column(BigInteger)
    applied_outbox_seq: Mapped[int | None] = mapped_column(BigInteger)
    total_objects: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    total_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    copied_objects: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    copied_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    verified_objects: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    failed_objects: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    throughput: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    pause_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    retry_failed_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    start_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    start_confirmed_by: Mapped[str | None] = mapped_column(Text)
    cutover_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cutover_confirmed_by: Mapped[str | None] = mapped_column(Text)
    cutover_committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    maintenance_window_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    estimate: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    report: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class StorageMigrationObject(Base):
    __tablename__ = "storage_migration_object"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    migration_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("storage_migration.id", ondelete="CASCADE"), nullable=False)
    namespace: Mapped[str] = mapped_column(Text, nullable=False)
    key: Mapped[str] = mapped_column(Text, nullable=False)
    expected_size: Mapped[int | None] = mapped_column(BigInteger)
    expected_sha256: Mapped[str | None] = mapped_column(Text)
    expected_version: Mapped[int | None] = mapped_column(BigInteger)
    source_seq: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    referenced: Mapped[bool | None] = mapped_column(Boolean)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    last_error: Mapped[str | None] = mapped_column(Text)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    copied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = _now()


class StorageMigrationEvent(Base):
    __tablename__ = "storage_migration_event"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    migration_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("storage_migration.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = _now()
    level: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'info'"))
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    actor_email: Mapped[str | None] = mapped_column(Text)
    from_state: Mapped[str | None] = mapped_column(Text)
    to_state: Mapped[str | None] = mapped_column(Text)
    message: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))


class MaintenanceWindow(Base):
    __tablename__ = "maintenance_window"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    block_scope: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'all'"))
    state: Mapped[str] = mapped_column(Text, nullable=False)
    reason_code: Mapped[str] = mapped_column(Text, nullable=False)
    affected_features: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    public_message: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    internal_note: Mapped[str | None] = mapped_column(Text)
    source_job_type: Mapped[str | None] = mapped_column(Text)
    source_job_id: Mapped[str | None] = mapped_column(Text)
    scheduled_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scheduled_end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    estimate: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    estimated_end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    original_estimated_end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    safety_margin_seconds: Mapped[int | None] = mapped_column(Integer)
    estimate_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    progress: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    release_conditions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    warnings: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_by_email: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _now()


class MaintenanceEvent(Base):
    __tablename__ = "maintenance_event"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    window_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("maintenance_window.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = _now()
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    actor_email: Mapped[str | None] = mapped_column(Text)
    from_state: Mapped[str | None] = mapped_column(Text)
    to_state: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
