"""Lesesicht auf logische Dokumente: Detail mit Versionen, Kurzstatus für den Dateien-Tab und
Zugriffsprüfung. Der Gesamtstatus wird aus den Aufträgen der aktuellen Version abgeleitet und
nicht gespeichert."""

from __future__ import annotations

import uuid
from collections import defaultdict

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import CurrentUser, require_abgabebox_read
from app.models import StoredFile, SubmissionUploadFile
from app.models.document_entities import (
    DOCUMENT_SOURCE_PROTOCOL_EXPORT,
    FILE_ROLE_ORIGINAL,
    FILE_ROLE_PDF,
    FILE_ROLE_PREVIEW,
    JOB_KIND_EXTRACT,
    JOB_KIND_PDF,
    Document,
    DocumentExtraction,
    DocumentFile,
    DocumentJob,
    DocumentVersion,
)
from app.schemas.documents import (
    DocumentDetail,
    DocumentExtractionRead,
    DocumentFileRead,
    DocumentJobState,
    DocumentSummary,
    DocumentVersionRead,
)
from app.services.access_service import AccessService

access_service = AccessService()

# Ergebnisse eines abgeschlossenen Extraktionsauftrags, die kein Fehler sind.
_EXTRACTION_OK = {"ready", "empty", "unsupported", "ocr_required"}


def file_url(document: Document, version: DocumentVersion, role: str, *, download: bool = False) -> str:
    url = f"/api/documents/{document.public_id}/versions/{version.public_id}/files/{role}"
    return f"{url}?download=1" if download else url


def text_url(document: Document, version: DocumentVersion) -> str:
    return f"/api/documents/{document.public_id}/versions/{version.public_id}/text"


def _job_state(job: DocumentJob | None) -> DocumentJobState:
    if job is None:
        return DocumentJobState(status="none")
    return DocumentJobState(status=job.status, result=job.result, attempts=job.attempts)


def overall_status(pdf_job: DocumentJob | None, extract_job: DocumentJob | None, extraction: DocumentExtraction | None, has_pdf: bool) -> str:
    jobs = [job for job in (pdf_job, extract_job) if job is not None]
    if any(job.status in ("queued", "running") for job in jobs):
        return "processing"
    pdf_ok = has_pdf or pdf_job is None or (pdf_job.status == "done" and pdf_job.result in ("unsupported", "already_pdf"))
    extraction_ok = extraction is not None and extraction.status in _EXTRACTION_OK
    if pdf_ok and extraction_ok:
        return "ready"
    if not has_pdf and (extraction is None or extraction.status == "failed"):
        return "failed"
    return "partial"


# ── Zugriff ───────────────────────────────────────────────────────────────────


def original_of(db: Session, version_id: int) -> StoredFile | None:
    return db.scalar(
        select(StoredFile)
        .join(DocumentFile, DocumentFile.stored_file_id == StoredFile.id)
        .where(DocumentFile.document_version_id == version_id, DocumentFile.role == FILE_ROLE_ORIGINAL)
    )


def get_document_for_user(db: Session, user: CurrentUser, document_id: uuid.UUID) -> Document:
    """Gleiche (oder strengere) Regeln wie die Originaldatei bzw. das Protokoll. Ein Dokument
    eines anderen Mandanten ist immer 404 - auch über geteilte Alben gibt es keinen Zugriff."""
    document = db.scalar(select(Document).where(Document.public_id == document_id))
    if document is None or user.current_tenant_id is None or document.tenant_id != user.current_tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dokument nicht gefunden")
    if document.source_kind == DOCUMENT_SOURCE_PROTOCOL_EXPORT:
        access_service.ensure_can_read_protocol(db, user, document.protocol_id)
        return document
    if document.current_version_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dokument nicht gefunden")
    original = original_of(db, document.current_version_id)
    if original is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dokument nicht gefunden")
    if db.scalar(select(SubmissionUploadFile.id).where(SubmissionUploadFile.stored_file_id == original.id).limit(1)) is not None:
        # Abgabebox-Dokumente zusätzlich nur mit gebuchter Abgabebox (wie die Abgabe-Dateiroute).
        require_abgabebox_read(user)
    access_service.ensure_can_read_stored_file(db, user, original.id)
    return document


def get_version(db: Session, document: Document, version_id: uuid.UUID) -> DocumentVersion:
    version = db.scalar(
        select(DocumentVersion).where(DocumentVersion.public_id == version_id, DocumentVersion.document_id == document.id)
    )
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version nicht gefunden")
    return version


# ── Detail ────────────────────────────────────────────────────────────────────


def _file_read(document: Document, version: DocumentVersion, role: str, stored_file: StoredFile | None) -> DocumentFileRead | None:
    if stored_file is None:
        return None
    return DocumentFileRead(
        name=stored_file.original_name,
        mime_type=stored_file.mime_type,
        size_bytes=stored_file.file_size_bytes,
        url=file_url(document, version, role),
        download_url=file_url(document, version, role, download=True),
    )


def build_detail(db: Session, document: Document, *, can_write: bool) -> DocumentDetail:
    versions = list(
        db.scalars(
            select(DocumentVersion).where(DocumentVersion.document_id == document.id).order_by(DocumentVersion.version_number.desc())
        )
    )
    version_ids = [version.id for version in versions]
    files: dict[int, dict[str, StoredFile]] = defaultdict(dict)
    for row, stored_file in db.execute(
        select(DocumentFile, StoredFile)
        .join(StoredFile, StoredFile.id == DocumentFile.stored_file_id)
        .where(DocumentFile.document_version_id.in_(version_ids))
    ).all():
        files[row.document_version_id][row.role] = stored_file
    jobs: dict[int, dict[str, DocumentJob]] = defaultdict(dict)
    for job in db.scalars(select(DocumentJob).where(DocumentJob.document_version_id.in_(version_ids))):
        jobs[job.document_version_id][job.kind] = job
    extractions = {
        extraction.document_version_id: extraction
        for extraction in db.scalars(select(DocumentExtraction).where(DocumentExtraction.document_version_id.in_(version_ids)))
    }

    version_reads = []
    for version in versions:
        extraction = extractions.get(version.id)
        version_reads.append(
            DocumentVersionRead(
                id=version.public_id,
                version_number=version.version_number,
                label=version.label,
                created_at=version.created_at,
                is_current=version.id == document.current_version_id,
                original=_file_read(document, version, FILE_ROLE_ORIGINAL, files[version.id].get(FILE_ROLE_ORIGINAL)),
                pdf=_file_read(document, version, FILE_ROLE_PDF, files[version.id].get(FILE_ROLE_PDF)),
                preview=_file_read(document, version, FILE_ROLE_PREVIEW, files[version.id].get(FILE_ROLE_PREVIEW)),
                pdf_job=_job_state(jobs[version.id].get(JOB_KIND_PDF)),
                extract_job=_job_state(jobs[version.id].get(JOB_KIND_EXTRACT)),
                extraction=DocumentExtractionRead(
                    status=extraction.status,
                    parser=extraction.parser,
                    parser_version=extraction.parser_version,
                    schema_version=extraction.schema_version,
                    page_count=extraction.page_count,
                    char_count=extraction.char_count,
                    ocr_applied=extraction.ocr_applied,
                    warnings=[str(warning) for warning in extraction.warnings or []],
                    error=extraction.error,
                    text_url=text_url(document, version) if extraction.status in ("ready", "ocr_required") else None,
                ) if extraction is not None else None,
            )
        )
    current = document.current_version_id
    current_jobs = jobs.get(current, {}) if current else {}
    status_value = overall_status(
        current_jobs.get(JOB_KIND_PDF), current_jobs.get(JOB_KIND_EXTRACT), extractions.get(current), FILE_ROLE_PDF in files.get(current, {})
    ) if current else "failed"
    current_version = next((version for version in versions if version.id == current), None)
    return DocumentDetail(
        id=document.public_id,
        display_name=document.display_name,
        source_kind=document.source_kind,
        status=status_value,
        created_at=document.created_at,
        updated_at=document.updated_at,
        current_version_id=current_version.public_id if current_version else None,
        versions=version_reads,
        can_reprocess=can_write and any(job.status in ("failed", "blocked") for job in current_jobs.values()),
    )


# ── Kurzstatus für den Dateien-Tab ───────────────────────────────────────────


def summaries_for_files(db: Session, tenant_id: int, stored_file_ids: list[int]) -> dict[int, DocumentSummary]:
    """stored_file.id (Original bzw. Export-PDF der aktuellen Version) -> Kurzstatus. Eine Abfrage
    je Tabelle für die ganze Seite."""
    if not stored_file_ids:
        return {}
    rows = db.execute(
        select(DocumentFile.stored_file_id, Document, DocumentVersion)
        .join(DocumentVersion, DocumentVersion.id == DocumentFile.document_version_id)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(
            DocumentFile.stored_file_id.in_(stored_file_ids),
            DocumentFile.role == FILE_ROLE_ORIGINAL,
            Document.tenant_id == tenant_id,
            Document.current_version_id == DocumentVersion.id,
        )
    ).all()
    if not rows:
        return {}
    version_ids = [version.id for _sid, _document, version in rows]
    document_ids = [document.id for _sid, document, _version in rows]
    jobs: dict[int, dict[str, DocumentJob]] = defaultdict(dict)
    for job in db.scalars(select(DocumentJob).where(DocumentJob.document_version_id.in_(version_ids))):
        jobs[job.document_version_id][job.kind] = job
    extractions = {
        row.document_version_id: row
        for row in db.scalars(select(DocumentExtraction).where(DocumentExtraction.document_version_id.in_(version_ids)))
    }
    roles_by_version: dict[int, set[str]] = defaultdict(set)
    for version_id, role in db.execute(
        select(DocumentFile.document_version_id, DocumentFile.role).where(
            DocumentFile.document_version_id.in_(version_ids), DocumentFile.role.in_((FILE_ROLE_PDF, FILE_ROLE_PREVIEW))
        )
    ).all():
        roles_by_version[version_id].add(role)
    counts = dict(
        db.execute(
            select(DocumentVersion.document_id, func.count()).where(DocumentVersion.document_id.in_(document_ids)).group_by(DocumentVersion.document_id)
        ).all()
    )
    result: dict[int, DocumentSummary] = {}
    for stored_file_id, document, version in rows:
        pdf_job = jobs[version.id].get(JOB_KIND_PDF)
        extract_job = jobs[version.id].get(JOB_KIND_EXTRACT)
        extraction = extractions.get(version.id)
        has_pdf = FILE_ROLE_PDF in roles_by_version[version.id]
        has_preview = FILE_ROLE_PREVIEW in roles_by_version[version.id]
        result[stored_file_id] = DocumentSummary(
            id=document.public_id,
            status=overall_status(pdf_job, extract_job, extraction, has_pdf),
            pdf_status="done" if has_pdf else _job_state(pdf_job).status,
            extraction_status=extraction.status if extraction is not None else (extract_job.status if extract_job else None),
            pdf_url=file_url(document, version, FILE_ROLE_PDF) if has_pdf else None,
            pdf_download_url=file_url(document, version, FILE_ROLE_PDF, download=True) if has_pdf else None,
            preview_url=file_url(document, version, FILE_ROLE_PREVIEW) if has_preview else None,
            version_count=counts.get(document.id, 1),
            current_version_number=version.version_number,
            current_version_label=version.label,
            detail_url=f"/api/documents/{document.public_id}",
        )
    return result
