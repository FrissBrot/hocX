"""Datei-Import (Migration 0230_cloud_import, services/cloud_import).

import_job: ein Import-Vorgang (Quelle ZIP oder Ordner-Upload, Regeln, Status, Lease).
import_item: eine Quelldatei mit Regel-Ergebnis und Ablaufstatus. Beide mit tenant_id + RLS.
Der Detailbericht (import_item) bleibt, solange mindestens eine importierte Datei existiert
(User-Entscheid E-12, Aufräumen in services/cloud_import/worker.py).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, SmallInteger, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

IMPORT_JOB_STATUSES = ("draft", "ready", "queued", "running", "cancel_requested", "cancelled", "done", "failed")
# Höchstens ein Auftrag je Mandant in diesen Zuständen (Partial Unique Index, E-5)
IMPORT_JOB_ACTIVE_STATUSES = ("draft", "ready", "queued", "running", "cancel_requested")
IMPORT_JOB_TERMINAL_STATUSES = ("cancelled", "done", "failed")
IMPORT_ITEM_STATUSES = ("listed", "queued", "staged", "imported", "duplicate", "skipped", "failed", "cancelled")


class ImportJob(Base):
    __tablename__ = "import_job"
    __table_args__ = (
        CheckConstraint(f"status IN {IMPORT_JOB_STATUSES}", name="ck_import_job_status"),
        CheckConstraint("source IN ('zip', 'folder')", name="ck_import_job_source"),
        CheckConstraint("type_filter IN ('all', 'images', 'documents')", name="ck_import_job_type_filter"),
        Index("idx_import_job_tenant", "tenant_id", text("created_at DESC")),
        Index("idx_import_job_status_lease", "status", "lease_until"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()"))
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    requested_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))
    source: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"))
    type_filter: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'all'"))
    include_gps: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"), default=True)
    folder_tags: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), default=False)
    takeout: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), default=False)
    rules: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list)
    # Gestagte ZIP-Archive: [{"path": <relativ zu storage_root>, "size": int}] (Name nie als Pfad)
    archives: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list)
    # Beim Import angelegte Alben: {"<Name>": "<album uuid>"}
    album_map: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict)
    total_items: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    total_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"), default=0)
    # Kuratierter Fehlercode (nie Ausnahme-Text)
    error: Mapped[str | None] = mapped_column(Text)
    lease_owner: Mapped[str | None] = mapped_column(Text)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    served_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_progress_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ImportItem(Base):
    __tablename__ = "import_item"
    __table_args__ = (
        CheckConstraint(f"status IN {IMPORT_ITEM_STATUSES}", name="ck_import_item_status"),
        CheckConstraint("kind IN ('image', 'document', 'other')", name="ck_import_item_kind"),
        UniqueConstraint("job_id", "path", name="uq_import_item_job_path"),
        Index("idx_import_item_job_status", "job_id", "status", "id"),
        Index("idx_import_item_tenant", "tenant_id"),
        Index("idx_import_item_stored_file", "stored_file_id", postgresql_where=text("stored_file_id IS NOT NULL")),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    job_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("import_job.id", ondelete="CASCADE"), nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"), default=0)
    modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archive_index: Mapped[int | None] = mapped_column(SmallInteger)
    entry_index: Mapped[int | None] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    # Grund aus dem Auflisten (zu gross, Format, Takeout-Metadaten …), sonst NULL
    listing_code: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'listed'"))
    result_code: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list)
    estimated_date: Mapped[date | None] = mapped_column(Date)
    albums: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list)
    matched_rules: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list)
    conflict: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), default=False)
    group_key: Mapped[str | None] = mapped_column(Text)
    staged_path: Mapped[str | None] = mapped_column(Text)
    stored_file_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("stored_file.id", ondelete="SET NULL"))
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"), default=0)
