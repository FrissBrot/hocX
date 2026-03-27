from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, HTTPException

from app.core.db import get_db
from app.schemas.protocol import ProtocolExportRead
from app.services.export_service import ExportService

router = APIRouter()
service = ExportService()


@router.post("/protocols/{protocol_id}/exports/latex", response_model=ProtocolExportRead)
def export_latex(protocol_id: int, db: Session = Depends(get_db)):
    try:
        return service.export_latex(db, protocol_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (SQLAlchemyError, RuntimeError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/protocols/{protocol_id}/exports/pdf", response_model=ProtocolExportRead)
def export_pdf(protocol_id: int, db: Session = Depends(get_db)):
    try:
        return service.export_pdf(db, protocol_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (SQLAlchemyError, RuntimeError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/protocols/{protocol_id}/exports/latest", response_model=ProtocolExportRead)
def latest_export(protocol_id: int, db: Session = Depends(get_db)):
    return service.latest_export_metadata(db, protocol_id)
