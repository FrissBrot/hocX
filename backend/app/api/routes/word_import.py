import json
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
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
)
from app.services.word_import_queue_service import WordImportQueueService
from app.services.word_import_service import WordImportService

router = APIRouter()
service = WordImportService()
queue_service = WordImportQueueService()


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
    if not file.filename or not file.filename.lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="Nur .docx-Dateien werden unterstützt")
    raw_bytes = await file.read()
    table_role_overrides: dict[int, dict] = {}
    if table_roles_json:
        try:
            table_role_overrides = {int(key): value for key, value in json.loads(table_roles_json).items()}
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail="Ungültige Tabellen-Zuordnung") from exc
    try:
        return service.analyze(
            db,
            tenant_id=user.current_tenant_id,
            template_id=template_id,
            protocol_date_hint=protocol_date_hint,
            raw_bytes=raw_bytes,
            table_role_overrides=table_role_overrides,
        )
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


def _to_summary(document: WordImportDocument, template_name: str) -> WordImportDocumentSummary:
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
    )


@router.post("/tools/word-import/documents", response_model=WordImportDocumentUploadResult, status_code=status.HTTP_201_CREATED)
async def ingest_word_import_documents(
    template_id: int = Form(...),
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    file_payloads: list[tuple[str, bytes]] = []
    errors: list[str] = []
    for file in files:
        if not file.filename or not file.filename.lower().endswith(".docx"):
            errors.append(f"{file.filename or 'Datei'}: Nur .docx-Dateien werden unterstützt")
            continue
        file_payloads.append((file.filename, await file.read()))

    try:
        documents, ingest_errors = queue_service.ingest(
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
        documents=[_to_summary(doc, template_name) for doc in documents],
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
    return [_to_summary(document, template_name) for document, template_name in rows]


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
    summary = _to_summary(document, template.name if template else "")
    return WordImportDocumentDetail(**summary.model_dump(), analysis=WordImportAnalysis(**document.analysis_snapshot_json))


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
