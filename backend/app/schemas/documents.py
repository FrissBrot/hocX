"""API-Schemas der logischen Dokumente (siehe app/services/document_read_service.py)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

DocumentStatus = Literal["processing", "ready", "partial", "failed"]
JobStatus = Literal["queued", "running", "done", "failed", "blocked", "none"]


class DocumentJobState(BaseModel):
    status: JobStatus
    # Fachliches Ergebnis (converted, already_pdf, unsupported, extracted, ocr_required, ...).
    result: str | None = None
    attempts: int = 0


class DocumentFileRead(BaseModel):
    name: str
    mime_type: str | None
    size_bytes: int | None
    url: str
    download_url: str


class DocumentExtractionRead(BaseModel):
    status: str
    parser: str | None
    parser_version: str | None
    schema_version: int
    page_count: int | None
    char_count: int | None
    ocr_applied: bool
    warnings: list[str]
    # Nur ein Code/Fehlertyp, nie Dokumentinhalt.
    error: str | None
    text_url: str | None


class DocumentVersionRead(BaseModel):
    id: uuid.UUID
    version_number: int
    label: str | None
    created_at: datetime
    is_current: bool
    original: DocumentFileRead | None
    pdf: DocumentFileRead | None
    # Bild der ersten PDF-Seite (Vorschau im Dateien-Tab).
    preview: DocumentFileRead | None = None
    pdf_job: DocumentJobState
    extract_job: DocumentJobState
    extraction: DocumentExtractionRead | None


class DocumentSummary(BaseModel):
    """Kurzform für den Dateien-Tab (FileOverviewItem.document)."""

    id: uuid.UUID
    status: DocumentStatus
    pdf_status: JobStatus
    extraction_status: str | None
    pdf_url: str | None
    pdf_download_url: str | None
    preview_url: str | None = None
    version_count: int
    current_version_number: int | None
    current_version_label: str | None
    detail_url: str


class DocumentDetail(BaseModel):
    id: uuid.UUID
    display_name: str
    source_kind: Literal["upload", "protocol_export"]
    status: DocumentStatus
    created_at: datetime
    updated_at: datetime
    current_version_id: uuid.UUID | None
    versions: list[DocumentVersionRead]
    can_reprocess: bool


class DocumentText(BaseModel):
    format: Literal["plain", "markdown", "json"]
    status: str
    text: str | None = None
    content: dict | None = None


class DocumentReprocessResult(BaseModel):
    requeued: int
