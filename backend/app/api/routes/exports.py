from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, HTTPException

from app.core.db import get_db
from app.core.security import CurrentUser, get_current_user, require_admin, require_reader
from app.schemas.protocol import ProtocolExportRead
from app.services.access_service import AccessService
from app.services.export_service import ExportService

router = APIRouter()
service = ExportService()
access_service = AccessService()


@router.post("/protocols/{protocol_id}/exports/latex", response_model=ProtocolExportRead)
def export_latex(
    protocol_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_admin(user)
    try:
        return service.export_latex(db, protocol_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (SQLAlchemyError, RuntimeError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/protocols/{protocol_id}/exports/pdf", response_model=ProtocolExportRead)
def export_pdf(
    protocol_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_reader(user)
    access_service.ensure_can_read_protocol(db, user, protocol_id)
    try:
        return service.export_pdf(db, protocol_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (SQLAlchemyError, RuntimeError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/protocols/{protocol_id}/exports/latest", response_model=ProtocolExportRead)
def latest_export(
    protocol_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_reader(user)
    access_service.ensure_can_read_protocol(db, user, protocol_id)
    return service.latest_export_metadata(db, protocol_id)
