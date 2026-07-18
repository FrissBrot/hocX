from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.db import get_db
from app.core.security import CurrentUser, get_current_user, require_admin, require_reader
from app.schemas.protocol import ProtocolExportRead
from app.services.access_service import AccessService
from app.services.export_service import ExportService

router = APIRouter()
service = ExportService()
access_service = AccessService()


class StandaloneExportRequest(BaseModel):
    template_id: int
    filter: str = "all"


class GlobalEventExportRequest(BaseModel):
    template_id: int
    tag_filters: list[str] = []
    until_date: str | None = None


class GlobalTodoExportRequest(BaseModel):
    template_id: int
    filter: str = "all"
    participant_id: int | None = None
    group_by_person: bool = False
    until_date: str | None = None


class GlobalListExportRequest(BaseModel):
    template_id: int
    list_definition_id: int
    group_by: str = ""
    sort_by: str = ""
    sort_direction: str = "asc"
    filter_column: str = ""
    filter_participant_id: int | None = None
    filter_event_id: int | None = None
    filter_text: str | None = None


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
async def export_pdf(
    protocol_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_reader(user)
    access_service.ensure_can_read_protocol(db, user, protocol_id)
    try:
        return await service.export_pdf(db, protocol_id)
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


@router.post("/protocols/{protocol_id}/exports/todo-list", response_model=ProtocolExportRead)
async def export_todo_list(
    protocol_id: int,
    body: StandaloneExportRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_reader(user)
    access_service.ensure_can_read_protocol(db, user, protocol_id)
    try:
        return await service.export_standalone_pdf(db, protocol_id, body.template_id, "todos", body.filter)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (SQLAlchemyError, RuntimeError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/protocols/{protocol_id}/exports/event-list", response_model=ProtocolExportRead)
async def export_event_list(
    protocol_id: int,
    body: StandaloneExportRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_reader(user)
    access_service.ensure_can_read_protocol(db, user, protocol_id)
    try:
        return await service.export_standalone_pdf(db, protocol_id, body.template_id, "events", body.filter)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (SQLAlchemyError, RuntimeError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/exports/todos", response_model=ProtocolExportRead)
async def export_global_todos(
    body: GlobalTodoExportRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_reader(user)
    try:
        return await service.export_global_pdf(
            db, user.current_tenant_id, body.template_id, "todos", body.filter,
            participant_id=body.participant_id, group_by_person=body.group_by_person,
            until_date=body.until_date,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (SQLAlchemyError, RuntimeError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/exports/lists", response_model=ProtocolExportRead)
async def export_global_list(
    body: GlobalListExportRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_reader(user)
    try:
        return await service.export_global_pdf(
            db, user.current_tenant_id, body.template_id, "list",
            list_definition_id=body.list_definition_id,
            list_group_by=body.group_by,
            list_sort_by=body.sort_by,
            list_sort_direction=body.sort_direction,
            list_filter_column=body.filter_column,
            list_filter_participant_id=body.filter_participant_id,
            list_filter_event_id=body.filter_event_id,
            list_filter_text=body.filter_text,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (SQLAlchemyError, RuntimeError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/exports/events", response_model=ProtocolExportRead)
async def export_global_events(
    body: GlobalEventExportRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_reader(user)
    try:
        return await service.export_global_pdf(
            db, user.current_tenant_id, body.template_id, "events",
            tag_filters=body.tag_filters, until_date=body.until_date,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (SQLAlchemyError, RuntimeError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
