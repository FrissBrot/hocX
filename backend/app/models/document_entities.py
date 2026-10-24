"""ORM-Modelle der logischen Dokumentebene (Migration 0115, docs-site/docs/technik/dokumente.md)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, deferred, mapped_column

from app.db.base import Base

DOCUMENT_SOURCE_UPLOAD = "upload"
DOCUMENT_SOURCE_PROTOCOL_EXPORT = "protocol_export"

FILE_ROLE_ORIGINAL = "original"
FILE_ROLE_PDF = "pdf"
# Bild der ersten PDF-Seite für die Vorschau im Dateien-Tab - die App erlaubt keine eingebetteten
# Frames (CSP frame-src 'none', X-Frame-Options DENY), das PDF selbst öffnet im eigenen Tab.
FILE_ROLE_PREVIEW = "preview"

JOB_KIND_PDF = "pdf"
JOB_KIND_EXTRACT = "extract"


def _now():
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))


class Document(Base):
    __tablename__ = "document"
    __table_args__ = (
        CheckConstraint("source_kind IN ('upload', 'protocol_export')", name="ck_document_source_kind"),
        CheckConstraint(
            "(source_kind = 'upload' AND protocol_id IS NULL AND export_kind IS NULL) OR "
            "(source_kind = 'protocol_export' AND protocol_id IS NOT NULL AND export_kind IS NOT NULL)",
            name="ck_document_source_identity",
        ),
        Index("idx_document_tenant", "tenant_id"),
        Index(
            "uq_document_protocol_export", "protocol_id", "export_kind", unique=True,
            postgresql_where=text("protocol_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    source_kind: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    # Explizit gesetzte aktuelle Version (siehe Migration 0115) - nie "neuester Zeitstempel".
    current_version_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("document_version.id", ondelete="SET NULL", use_alter=True, name="fk_document_current_version")
    )
    protocol_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("protocol.id", ondelete="CASCADE"))
    export_kind: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _now()


class DocumentVersion(Base):
    __tablename__ = "document_version"
    __table_args__ = (
        CheckConstraint("version_number >= 1", name="ck_document_version_number"),
        UniqueConstraint("document_id", "version_number", name="uq_document_version_number"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    document_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("document.id", ondelete="CASCADE"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str | None] = mapped_column(Text)
    content_fingerprint: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _now()


class DocumentFile(Base):
    __tablename__ = "document_file"
    __table_args__ = (
        CheckConstraint("role IN ('original', 'pdf', 'preview')", name="ck_document_file_role"),
        UniqueConstraint("document_version_id", "role", name="uq_document_file_version_role"),
        Index("idx_document_file_stored_file", "stored_file_id"),
        Index("uq_document_file_original", "stored_file_id", unique=True, postgresql_where=text("role = 'original'")),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    document_version_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("document_version.id", ondelete="CASCADE"), nullable=False
    )
    stored_file_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("stored_file.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    is_generated: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), default=False)
    created_at: Mapped[datetime] = _now()


class DocumentExtraction(Base):
    __tablename__ = "document_extraction"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ready', 'empty', 'ocr_required', 'unsupported', 'failed')", name="ck_document_extraction_status"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    document_version_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("document_version.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    status: Mapped[str] = mapped_column(Text, nullable=False)
    parser: Mapped[str | None] = mapped_column(Text)
    parser_version: Mapped[str | None] = mapped_column(Text)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"), default=1)
    # Gross - nur laden, wenn wirklich gebraucht (Detailansicht, spätere Zusammenführung).
    content: Mapped[dict[str, Any] | None] = deferred(mapped_column(JSONB))
    plain_text: Mapped[str | None] = deferred(mapped_column(Text))
    page_count: Mapped[int | None] = mapped_column(Integer)
    char_count: Mapped[int | None] = mapped_column(Integer)
    ocr_applied: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), default=False)
    warnings: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _now()


class DocumentJob(Base):
    __tablename__ = "document_job"
    __table_args__ = (
        CheckConstraint("kind IN ('pdf', 'extract')", name="ck_document_job_kind"),
        CheckConstraint("status IN ('queued', 'running', 'done', 'failed', 'blocked')", name="ck_document_job_status"),
        UniqueConstraint("document_version_id", "kind", name="uq_document_job_version_kind"),
        Index("idx_document_job_queued", "run_after", postgresql_where=text("status = 'queued'")),
        Index("idx_document_job_running", "lease_expires_at", postgresql_where=text("status = 'running'")),
        Index("idx_document_job_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    document_version_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("document_version.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'queued'"), default="queued")
    result: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("5"), default=5)
    run_after: Mapped[datetime] = _now()
    lease_owner: Mapped[str | None] = mapped_column(Text)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _now()


class DocumentRenderJob(Base):
    """PDF-Export als Auftrag (Migration 0150, services/document_render_jobs.py). Rendert der
    job-worker; das Frontend fragt den Stand ab und meldet "PDF bereit"."""

    __tablename__ = "document_render_job"
    __table_args__ = (
        CheckConstraint("status IN ('queued', 'running', 'done', 'failed')", name="ck_document_render_job_status"),
        Index("idx_document_render_job_queue", "status", "created_at"),
        Index("idx_document_render_job_tenant", "tenant_id", text("created_at DESC")),
        Index("idx_document_render_job_protocol", "protocol_id", postgresql_where=text("protocol_id IS NOT NULL")),
        Index("idx_document_render_job_export", "export_id", postgresql_where=text("export_id IS NOT NULL")),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()"))
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)
    requested_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))
    protocol_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("protocol.id", ondelete="CASCADE"))
    request_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'queued'"), default="queued")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"), default=0)
    export_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("document_export.id", ondelete="SET NULL"))
    error_status: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[Any | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _now()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
