"""Upload-Verlauf (Migrationen 0250_upload_history ff., services/upload_job_service.py).

upload_job: ein Upload-Vorgang, wie ihn die Person erlebt (Kanal, Bezug, Status, Zähler).
upload_job_item: eine Datei des Vorgangs mit Ergebnis und Grund. Beide mit tenant_id + RLS; das
Item hängt über (tenant_id, upload_job_id) am Vorgang desselben Mandanten.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import ARRAY, BigInteger, Boolean, Date, DateTime, ForeignKey, ForeignKeyConstraint, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

UPLOAD_CHANNELS = (
    "gallery", "document", "protocol_image", "todo", "submission_link", "abgabebox", "word_import", "tenant_import", "cloud_import",
)
UPLOAD_JOB_STATUSES = ("open", "processing", "done", "partial", "failed", "cancelled")
UPLOAD_JOB_ACTIVE_STATUSES = ("open", "processing")
UPLOAD_ITEM_STATUSES = ("uploaded", "duplicate", "metadata_updated", "rejected", "infected", "failed", "discarded")


class UploadJob(Base):
    __tablename__ = "upload_job"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()"))
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    actor_kind: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'user'"), default="user")
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))
    # Knappe Zusatzangaben ohne Personendaten ({provider}, {submission_link: true} …)
    actor_ref: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict)
    event_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("event.id", ondelete="SET NULL"))
    submission_assignment_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("submission_assignment.id", ondelete="SET NULL"))
    submission_element_ref: Mapped[str | None] = mapped_column(Text)
    submission_element_label: Mapped[str | None] = mapped_column(Text)
    cycle_config_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("cycle_config.id", ondelete="SET NULL"))
    protocol_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("protocol.id", ondelete="SET NULL"))
    protocol_todo_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("protocol_todo.id", ondelete="SET NULL"))
    submission_upload_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("submission_upload.id", ondelete="SET NULL"))
    # FK (tenant_id, import_job_id) -> import_job, ON DELETE SET NULL nur für diese Spalte (0250)
    import_job_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    # Abgabebox: eine Anfrage, deren Dateien abgelehnt oder doppelt waren (Migration 0254, Trigger)
    request_ref: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    # Protokollbilder: ein Vorgang je Protokoll und Tag (E-6)
    group_day: Mapped[date | None] = mapped_column(Date)
    # Auszug der Upload-Optionen (Tags, Schätzdatum, include_gps …) - nie GPS-Werte oder Browser-Hinweise
    options: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'open'"), default="open")
    total: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    uploaded: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    duplicates: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    metadata_updated: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    rejected: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    infected: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    failed: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    discarded: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    reconstructed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    client_closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UploadJobItem(Base):
    __tablename__ = "upload_job_item"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "upload_job_id"], ["upload_job.tenant_id", "upload_job.id"], ondelete="CASCADE", name="fk_upload_job_item_job"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    upload_job_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    original_name: Mapped[str | None] = mapped_column(Text)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    mime_type: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    reason_code: Mapped[str | None] = mapped_column(Text)
    reason_params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict)
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'server'"), default="server")
    stored_file_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("stored_file.id", ondelete="SET NULL"))
    existing_file_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("stored_file.id", ondelete="SET NULL"))
    applied: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default=text("'{}'"), default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class CaptureChangeBatch(Base):
    """Eine Datumskorrektur der Mehrfachauswahl (Migration 0251) - Grundlage für «Rückgängig»."""

    __tablename__ = "capture_change_batch"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "upload_job_id"], ["upload_job.tenant_id", "upload_job.id"], name="fk_capture_change_batch_upload_job"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()"))
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict)
    upload_job_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    updated_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    undone_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))


class CaptureChangeItem(Base):
    __tablename__ = "capture_change_item"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "batch_id"], ["capture_change_batch.tenant_id", "capture_change_batch.id"], ondelete="CASCADE",
            name="fk_capture_change_item_batch",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    batch_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    stored_file_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("stored_file.id", ondelete="CASCADE"), nullable=False)
    prev_corrected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    prev_has_time: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), default=False)
    new_corrected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    new_has_time: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), default=False)


class CameraSerialBackfill(Base):
    """Fortschritt des Jobs camera_serial_backfill je Mandant (Migration 0253)."""

    __tablename__ = "camera_serial_backfill"

    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), primary_key=True)
    upper_file_id: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"), default=0)
    last_file_id: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"), default=0)
    checked: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    keyed: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    no_serial: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    missing: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    failed: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
