"""ORM-Modelle des Backup-Systems (Migration 0115, docs-site/docs/technik/backup/architektur.md)."""

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


def _jsonb(default: str = "'{}'::jsonb"):
    return mapped_column(JSONB, nullable=False, server_default=text(default))


class BackupSettings(Base):
    __tablename__ = "backup_settings"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    schedule_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    interval_hours: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("6"))
    schedule_offset_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("15"))
    keep_within_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("14"))
    keep_daily: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("14"))
    keep_weekly: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("8"))
    keep_monthly: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("12"))
    verify_interval_hours: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("168"))
    verify_sample_objects: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("200"))
    restore_test_interval_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("30"))
    success_notification: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'daily'"))
    last_daily_summary_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    repository_status: Mapped[dict[str, Any]] = _jsonb()
    repository_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    worker_config: Mapped[dict[str, Any]] = _jsonb()
    updated_at: Mapped[datetime] = _now()
    updated_by_email: Mapped[str | None] = mapped_column(Text)


class _LeaseMixin:
    lease_owner: Mapped[str | None] = mapped_column(Text)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fencing_token: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    progress: Mapped[dict[str, Any]] = _jsonb()
    checkpoint: Mapped[dict[str, Any]] = _jsonb()
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = _now()


class BackupSet(Base):
    __tablename__ = "backup_set"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    archive_name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    archive_id: Mapped[str | None] = mapped_column(Text)
    job_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("backup_job.id", ondelete="SET NULL", use_alter=True))
    state: Mapped[str] = mapped_column(Text, nullable=False)
    trigger: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'schedule'"))
    protected: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    protected_reason: Mapped[str | None] = mapped_column(Text)
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    app_version: Mapped[str | None] = mapped_column(Text)
    alembic_revision: Mapped[str | None] = mapped_column(Text)
    pg_server_version: Mapped[str | None] = mapped_column(Text)
    profile_name: Mapped[str | None] = mapped_column(Text)
    profile_provider: Mapped[str | None] = mapped_column(Text)
    generation: Mapped[int | None] = mapped_column(BigInteger)
    outbox_seq: Mapped[int | None] = mapped_column(BigInteger)
    db_dump_bytes: Mapped[int | None] = mapped_column(BigInteger)
    db_dump_sha256: Mapped[str | None] = mapped_column(Text)
    manifest_sha256: Mapped[str | None] = mapped_column(Text)
    object_count: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    object_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    new_object_count: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    new_object_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    deduplicated_bytes: Mapped[int | None] = mapped_column(BigInteger)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    pool_archives: Mapped[list[Any]] = _jsonb("'[]'::jsonb")
    tenants: Mapped[list[Any]] = _jsonb("'[]'::jsonb")
    warnings: Mapped[list[Any]] = _jsonb("'[]'::jsonb")
    verify_state: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'unverified'"))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verify_details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    restore_test_state: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'untested'"))
    restore_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    restore_test_details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    pruned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reconstructed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _now()


class BackupJob(_LeaseMixin, Base):
    __tablename__ = "backup_job"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    trigger: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'queued'"))
    idempotency_key: Mapped[str | None] = mapped_column(Text, unique=True)
    requested_by_email: Mapped[str | None] = mapped_column(Text)
    backup_set_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("backup_set.id", ondelete="SET NULL"))
    options: Mapped[dict[str, Any]] = _jsonb()
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))


class BackupPoolArchive(Base):
    __tablename__ = "backup_pool_archive"

    name: Mapped[str] = mapped_column(Text, primary_key=True)
    archive_id: Mapped[str | None] = mapped_column(Text)
    backup_set_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    state: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    object_count: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    total_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _now()


class BackupContent(Base):
    __tablename__ = "backup_content"

    sha256: Mapped[str] = mapped_column(Text, primary_key=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    pool_archive: Mapped[str] = mapped_column(Text, ForeignKey("backup_pool_archive.name", ondelete="CASCADE"), nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    created_at: Mapped[datetime] = _now()


class BackupRestoreJob(_LeaseMixin, Base):
    __tablename__ = "backup_restore_job"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'queued'"))
    idempotency_key: Mapped[str | None] = mapped_column(Text, unique=True)
    backup_set_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("backup_set.id", ondelete="SET NULL"))
    archive_name: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[dict[str, Any]] = _jsonb()
    plan: Mapped[dict[str, Any]] = _jsonb()
    requested_by_email: Mapped[str | None] = mapped_column(Text)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mfa_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BackupEvent(Base):
    __tablename__ = "backup_event"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("backup_job.id", ondelete="CASCADE"))
    restore_job_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("backup_restore_job.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = _now()
    level: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'info'"))
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    actor_email: Mapped[str | None] = mapped_column(Text)
    message: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = _jsonb()
