import json
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import CurrentUser, get_current_user, require_writer
from app.models import Template, WordImportDocument
from app.schemas.word_import import (
    WordImportAnalysis,
    WordImportCommit,
    WordImportDocumentDetail,
    WordImportDocumentReanalyzeRequest,
    WordImportDocumentSummary,
    WordImportDocumentUploadResult,
    WordImportDraftSave,
    WordImportDuplicateCandidate,
    WordImportQualityBucket,
    WordImportQualityStats,
)
from app.services.file_service import MAX_UPLOAD_BYTES, MAX_ZIP_TOTAL_BYTES, extract_word_import_files_from_zip
from app.services.word_import_quality_service import WordImportQualityService
from app.services.word_import_queue_service import WordImportQueueService
from app.services.word_import_service import WordImportService

router = APIRouter()
service = WordImportService()
queue_service = WordImportQueueService()
quality_service = WordImportQualityService()

# Ganzer Batch (Summe aller akzeptierten Dateien eines Upload-Requests, ausserhalb von
# ZIPs - deren eigener Grenzwert ist MAX_ZIP_TOTAL_BYTES): grösszügiger als eine einzelne
# Datei, aber trotzdem endlich, damit ein Request mit vielen knapp-unter-dem-Limit-Dateien
# nicht beliebig viel RAM/Platte/Parse-Zeit binden kann.
MAX_WORD_IMPORT_BATCH_FILES = 50
MAX_WORD_IMPORT_BATCH_BYTES = 150 * 1024 * 1024


async def _read_upload_within_limit(file: UploadFile, max_bytes: int) -> bytes | None:
    """Rejects an oversized upload using Starlette's already-known `.size` (populated by
    the multipart parser before the route runs, see UploadFile.write) instead of buffering
    the whole thing into a `bytes` object first just to measure it - a file that's already
    over the limit never gets fully materialized in memory this way. Returns None if too
    large."""
    if file.size is not None and file.size > max_bytes:
        return None
    content = await file.read()
    if len(content) > max_bytes:
        return None
    return content


@router.post("/tools/word-import/analyze", response_model=WordImportAnalysis)
async def analyze_word_import(
    file: UploadFile = File(...),
    template_id: int = Form(...),
    protocol_date_hint: date | None = Form(None),
    table_roles_json: str | None = Form(None),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    if not file.filename or not file.filename.lower().endswith((".docx", ".pdf")):
        raise HTTPException(status_code=400, detail="Nur .docx- oder .pdf-Dateien werden unterstützt")
    raw_bytes = await _read_upload_within_limit(file, MAX_UPLOAD_BYTES)
    if raw_bytes is None:
        raise HTTPException(status_code=413, detail=f"Datei zu gross. Maximum {MAX_UPLOAD_BYTES // 1024 // 1024} MB")
    table_role_overrides: dict[int, dict] = {}
    if table_roles_json:
        try:
            table_role_overrides = {int(key): value for key, value in json.loads(table_roles_json).items()}
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail="Ungültige Tabellen-Zuordnung") from exc
    try:
        # Ausgelagert in einen Threadpool-Worker statt direkt im Event-Loop ausgeführt -
        # WordImportService.analyze() ist eine synchrone Funktion, die u.a. das Parsen des
        # Dokuments anstösst (siehe parse_document_isolated() in word_import_service.py,
        # das seinerseits pathologische Dateien in einem eigenen, hart abbrechbaren
        # Subprozess parst). Ohne dieses Auslagern würde ein einziger blockierender
        # analyze()-Aufruf einen der nur zwei uvicorn-Worker-Prozesse für ALLE Mandanten
        # gleichzeitig blockieren.
        return await run_in_threadpool(
            service.analyze,
            db,
            tenant_id=user.current_tenant_id,
            template_id=template_id,
            protocol_date_hint=protocol_date_hint,
            raw_bytes=raw_bytes,
            table_role_overrides=table_role_overrides,
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Datei konnte nicht gelesen werden") from exc


@router.post("/tools/word-import/commit", response_model=dict[str, int], status_code=status.HTTP_201_CREATED)
def commit_word_import(
    payload: WordImportCommit,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    try:
        protocol_id = service.commit(db, tenant_id=user.current_tenant_id, user_id=user.user_id, payload=payload)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Protokoll konnte nicht erstellt werden") from exc
    return {"id": protocol_id}


def _to_summary(
    document: WordImportDocument, template_name: str, duplicates: list[WordImportDocument] | None = None
) -> WordImportDocumentSummary:
    return WordImportDocumentSummary(
        id=document.id,
        template_id=document.template_id,
        template_name=template_name,
        display_name=document.display_name,
        original_filename=document.original_filename,
        status=document.status,
        protocol_id=document.protocol_id,
        protocol_date=document.protocol_date,
        created_at=document.created_at,
        imported_at=document.imported_at,
        stored_file_id=document.stored_file_id,
        duplicates=[WordImportDuplicateCandidate.model_validate(dup) for dup in duplicates or []],
    )


@router.post("/tools/word-import/documents", response_model=WordImportDocumentUploadResult, status_code=status.HTTP_201_CREATED)
async def ingest_word_import_documents(
    template_id: int = Form(...),
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    if len(files) > MAX_WORD_IMPORT_BATCH_FILES:
        raise HTTPException(
            status_code=413,
            detail=f"Zu viele Dateien in einem Batch (maximal {MAX_WORD_IMPORT_BATCH_FILES})",
        )

    file_payloads: list[tuple[str, bytes]] = []
    errors: list[str] = []
    batch_bytes = 0
    for file in files:
        name = file.filename or ""
        lower = name.lower()
        if batch_bytes > MAX_WORD_IMPORT_BATCH_BYTES:
            errors.append(f"{name or 'Datei'}: übersprungen - Gesamtgrösse des Batches überschritten")
            continue
        if lower.endswith(".zip"):
            zip_bytes = await _read_upload_within_limit(file, MAX_ZIP_TOTAL_BYTES)
            if zip_bytes is None:
                errors.append(f"{name}: ZIP-Datei zu gross (maximal {MAX_ZIP_TOTAL_BYTES // 1024 // 1024} MB)")
                continue
            matched, notes = extract_word_import_files_from_zip(zip_bytes)
            file_payloads.extend(matched)
            batch_bytes += sum(len(content) for _, content in matched)
            errors.extend(f"{name}: {note}" for note in notes)
            continue
        if not name or not lower.endswith((".docx", ".pdf")):
            errors.append(f"{name or 'Datei'}: Nur .docx-, .pdf- oder .zip-Dateien werden unterstützt")
            continue
        content = await _read_upload_within_limit(file, MAX_UPLOAD_BYTES)
        if content is None:
            errors.append(f"{name}: zu gross (maximal {MAX_UPLOAD_BYTES // 1024 // 1024} MB)")
            continue
        file_payloads.append((name, content))
        batch_bytes += len(content)

    try:
        # Siehe Kommentar bei analyze_word_import oben - queue_service.ingest() ruft
        # dieselbe synchrone analyze()-Kette für jede Datei des Batches nacheinander auf,
        # muss also ebenso aus dem Event-Loop ausgelagert werden.
        documents, ingest_errors = await run_in_threadpool(
            queue_service.ingest,
            db,
            tenant_id=user.current_tenant_id,
            template_id=template_id,
            created_by=user.user_id,
            files=file_payloads,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    template = db.get(Template, template_id)
    template_name = template.name if template else ""
    return WordImportDocumentUploadResult(
        documents=[
            _to_summary(doc, template_name, queue_service.duplicates_for_document(db, doc)) for doc in documents
        ],
        errors=errors + ingest_errors,
    )


@router.get("/tools/word-import/documents", response_model=list[WordImportDocumentSummary])
def list_word_import_documents(
    status_filter: str | None = None,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    rows = queue_service.list_documents(db, tenant_id=user.current_tenant_id, status=status_filter)
    return [_to_summary(document, template_name, duplicates) for document, template_name, duplicates in rows]


@router.get("/tools/word-import/documents/{document_id}", response_model=WordImportDocumentDetail)
def get_word_import_document(
    document_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    document = queue_service.get_document(db, tenant_id=user.current_tenant_id, document_id=document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Dokument nicht gefunden")
    template = db.get(Template, document.template_id)
    duplicates = queue_service.duplicates_for_document(db, document)
    summary = _to_summary(document, template.name if template else "", duplicates)
    return WordImportDocumentDetail(
        **summary.model_dump(),
        analysis=WordImportAnalysis(**document.analysis_snapshot_json),
        review_draft=document.review_draft_json,
    )


@router.put("/tools/word-import/documents/{document_id}/draft", response_model=dict[str, str])
def save_word_import_document_draft(
    document_id: int,
    payload: WordImportDraftSave,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    document = queue_service.get_document(db, tenant_id=user.current_tenant_id, document_id=document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Dokument nicht gefunden")
    try:
        queue_service.save_draft(db, document=document, draft=payload.draft)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"message": "Entwurf gespeichert"}


@router.post("/tools/word-import/documents/{document_id}/reanalyze", response_model=WordImportAnalysis)
def reanalyze_word_import_document(
    document_id: int,
    payload: WordImportDocumentReanalyzeRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    document = queue_service.get_document(db, tenant_id=user.current_tenant_id, document_id=document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Dokument nicht gefunden")
    try:
        return queue_service.reanalyze(
            db, document=document, protocol_date=payload.protocol_date, table_role_overrides=payload.table_roles
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/tools/word-import/documents/{document_id}/commit", response_model=dict[str, int], status_code=status.HTTP_201_CREATED)
def commit_word_import_document(
    document_id: int,
    payload: WordImportCommit,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    document = queue_service.get_document(db, tenant_id=user.current_tenant_id, document_id=document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Dokument nicht gefunden")
    try:
        protocol_id = queue_service.commit_document(
            db, document=document, tenant_id=user.current_tenant_id, user_id=user.user_id, payload=payload
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Protokoll konnte nicht erstellt werden") from exc
    return {"id": protocol_id}


@router.delete("/tools/word-import/documents/{document_id}", response_model=dict[str, str])
def delete_word_import_document(
    document_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    try:
        deleted = queue_service.delete_document(db, tenant_id=user.current_tenant_id, document_id=document_id)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Dokument nicht gefunden")
    return {"message": "Dokument entfernt"}


@router.get("/tools/word-import/quality-stats", response_model=WordImportQualityStats)
def get_word_import_quality_stats(
    template_id: int | None = None,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    buckets = quality_service.accept_rate_stats(db, tenant_id=user.current_tenant_id, template_id=template_id)
    return WordImportQualityStats(buckets=[WordImportQualityBucket(**bucket) for bucket in buckets])
