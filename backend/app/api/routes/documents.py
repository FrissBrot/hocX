"""Logische Dokumente: Details mit Versionshistorie, PDF-/Original-Dateien je Version, extrahierter
Text und erneute Verarbeitung (siehe docs-site/docs/technik/dokumente.md).

Zugriff wie auf die Originaldatei bzw. das Protokoll (document_read_service.get_document_for_user),
nie mandantenübergreifend. Dateien werden nur ausgeliefert, wenn die Virenprüfung der Datei und
des Originals abgeschlossen und sauber ist."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import CurrentUser, get_current_user, require_reader, require_writer
from app.core.storage import object_response
from app.models import StoredFile
from app.models.document_entities import DocumentExtraction, DocumentFile
from app.schemas.documents import DocumentDetail, DocumentReprocessResult, DocumentText
from app.services import document_read_service, document_service
from app.services.documents.content import to_markdown
from app.services.stored_file_location import namespace_for_stored_file

router = APIRouter()


def _ensure_clean(stored_file: StoredFile) -> None:
    if stored_file.scan_status == "infected":
        raise HTTPException(status_code=403, detail="Datei wurde von der Virenprüfung als infiziert erkannt und ist gesperrt")
    if stored_file.scan_status == "error":
        raise HTTPException(status_code=422, detail="Virenprüfung fehlgeschlagen – Datei ist gesperrt")
    if stored_file.scan_status == "pending":
        raise HTTPException(status_code=425, detail="Datei wird noch auf Schadsoftware geprüft, bitte in Kürze erneut versuchen")


@router.get("/documents/{document_id}", response_model=DocumentDetail)
def get_document(document_id: uuid.UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_reader(user)
    document = document_read_service.get_document_for_user(db, user, document_id)
    return document_read_service.build_detail(db, document, can_write=user.current_role in {"admin", "writer"})


@router.get("/documents/{document_id}/versions/{version_id}/files/{role}")
def get_document_file(
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    role: Literal["pdf", "original"],
    request: Request = None,  # type: ignore[assignment]  # None nur bei direktem Aufruf in Tests
    download: bool = Query(default=False),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_reader(user)
    document = document_read_service.get_document_for_user(db, user, document_id)
    version = document_read_service.get_version(db, document, version_id)
    stored_file = db.scalar(
        select(StoredFile)
        .join(DocumentFile, DocumentFile.stored_file_id == StoredFile.id)
        .where(DocumentFile.document_version_id == version.id, DocumentFile.role == role)
    )
    if stored_file is None or stored_file.tenant_id != document.tenant_id:
        raise HTTPException(status_code=404, detail="Datei nicht vorhanden")
    _ensure_clean(stored_file)
    original = document_read_service.original_of(db, version.id)
    if original is not None:
        # Eine erzeugte Darstellung ist nie freier zugänglich als ihr Original.
        _ensure_clean(original)
    # Inline nur für verifizierte PDFs; alles andere als Download, nie MIME-Sniffing.
    is_pdf = (stored_file.mime_type or "").lower() == "application/pdf"
    return object_response(
        request,
        namespace_for_stored_file(db, stored_file),
        stored_file.storage_path,
        media_type=stored_file.mime_type or "application/octet-stream",
        filename=stored_file.original_name,
        attachment=download or not is_pdf,
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=3600"},
        not_found_detail="Datei fehlt im Speicher",
    )


@router.get("/documents/{document_id}/versions/{version_id}/text", response_model=DocumentText)
def get_document_text(
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    format: Literal["plain", "markdown", "json"] = Query(default="plain"),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_reader(user)
    document = document_read_service.get_document_for_user(db, user, document_id)
    version = document_read_service.get_version(db, document, version_id)
    original = document_read_service.original_of(db, version.id)
    if original is not None:
        _ensure_clean(original)
    extraction = db.scalar(select(DocumentExtraction).where(DocumentExtraction.document_version_id == version.id))
    if extraction is None:
        raise HTTPException(status_code=404, detail="Noch kein extrahierter Text vorhanden")
    if extraction.content is None:
        return DocumentText(format=format, status=extraction.status)
    if format == "json":
        return DocumentText(format=format, status=extraction.status, content=extraction.content)
    if format == "markdown":
        return DocumentText(format=format, status=extraction.status, text=to_markdown(extraction.content))
    return DocumentText(format=format, status=extraction.status, text=extraction.plain_text)


@router.post("/documents/{document_id}/reprocess", response_model=DocumentReprocessResult)
def reprocess_document(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Fehlgeschlagene/gesperrte Verarbeitung der aktuellen Version erneut einreihen."""
    require_writer(user)
    document = document_read_service.get_document_for_user(db, user, document_id)
    try:
        requeued = document_service.requeue_failed(db, document)
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Verarbeitung konnte nicht neu gestartet werden") from exc
    return DocumentReprocessResult(requeued=requeued)

