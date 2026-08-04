import json
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import CurrentUser, get_current_user, require_writer
from app.schemas.word_import import WordImportAnalysis, WordImportCommit
from app.services.word_import_service import WordImportService

router = APIRouter()
service = WordImportService()


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
