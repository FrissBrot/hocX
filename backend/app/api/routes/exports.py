import uuid

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.core.db import get_db
from app.core.error_log import record_system_error
from app.core.security import CurrentUser, get_current_user, require_admin, require_reader
from app.models.entities import Event, ListDefinition, Participant, Protocol, Template
from app.schemas.protocol import MarkdownExportRead, ProtocolExportRead
from app.services import public_id_service
from app.services.access_service import AccessService
from app.services.audit_service import AuditService
from app.services.export_service import ExportService

router = APIRouter()
service = ExportService()
access_service = AccessService()
audit = AuditService()

_EXPORT_FAILED_MESSAGE = "Export fehlgeschlagen. Bitte später erneut versuchen."


class StandaloneExportRequest(BaseModel):
    template_id: uuid.UUID
    filter: str = "all"


class GlobalEventExportRequest(BaseModel):
    template_id: uuid.UUID
    tag_filters: list[str] = []
    until_date: str | None = None


class GlobalTodoExportRequest(BaseModel):
    template_id: uuid.UUID
    filter: str = "all"
    participant_id: uuid.UUID | None = None
    group_by_person: bool = False
    until_date: str | None = None


class GlobalTodoMarkdownExportRequest(BaseModel):
    filter: str = "all"
    participant_id: uuid.UUID | None = None
    group_by_person: bool = False
    until_date: str | None = None
    date_summary: str | None = None


class GlobalListExportRequest(BaseModel):
    template_id: uuid.UUID
    list_definition_id: uuid.UUID
    group_by: str = ""
    sort_by: str = ""
    sort_direction: str = "asc"
    filter_column: str = ""
    filter_participant_id: uuid.UUID | None = None
    filter_event_id: uuid.UUID | None = None
    filter_text: str | None = None


def _resolve(db: Session, model: type, public_id: uuid.UUID, user: CurrentUser, *, label: str) -> int:
    internal_id = public_id_service.resolve_internal_id(db, model, public_id, tenant_id=user.current_tenant_id)
    if internal_id is None:
        raise HTTPException(status_code=404, detail=f"{label} not found")
    return internal_id


@router.post("/protocols/{protocol_id}/exports/latex", response_model=ProtocolExportRead)
def export_latex(
    protocol_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_admin(user)
    protocol_id = _resolve(db, Protocol, protocol_id, user, label="Protocol")
    access_service.ensure_can_read_protocol(db, user, protocol_id)
    try:
        result = service.export_latex(db, protocol_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (SQLAlchemyError, RuntimeError) as exc:
        db.rollback()
        record_system_error(db, exc=exc, request=request, tenant_id=user.current_tenant_id, actor_email=user.email, status_code=400)
        raise HTTPException(status_code=400, detail=_EXPORT_FAILED_MESSAGE) from exc
    audit.log(db, action="export.protocol_latex", actor=user, entity_type="protocol", entity_id=protocol_id)
    return result


@router.post("/protocols/{protocol_id}/exports/pdf", response_model=ProtocolExportRead)
async def export_pdf(
    protocol_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_reader(user)
    protocol_id = _resolve(db, Protocol, protocol_id, user, label="Protocol")
    access_service.ensure_can_read_protocol(db, user, protocol_id)
    try:
        result = await service.export_pdf(db, protocol_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (SQLAlchemyError, RuntimeError) as exc:
        db.rollback()
        record_system_error(db, exc=exc, request=request, tenant_id=user.current_tenant_id, actor_email=user.email, status_code=400)
        raise HTTPException(status_code=400, detail=_EXPORT_FAILED_MESSAGE) from exc
    audit.log(db, action="export.protocol_pdf", actor=user, entity_type="protocol", entity_id=protocol_id)
    return result


@router.get("/protocols/{protocol_id}/exports/latest", response_model=ProtocolExportRead)
def latest_export(
    protocol_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_reader(user)
    protocol_id = _resolve(db, Protocol, protocol_id, user, label="Protocol")
    access_service.ensure_can_read_protocol(db, user, protocol_id)
    return service.latest_export_metadata(db, protocol_id)


@router.post("/protocols/{protocol_id}/exports/todo-list", response_model=ProtocolExportRead)
async def export_todo_list(
    protocol_id: uuid.UUID,
    body: StandaloneExportRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_reader(user)
    protocol_id = _resolve(db, Protocol, protocol_id, user, label="Protocol")
    template_id = _resolve(db, Template, body.template_id, user, label="Template")
    access_service.ensure_can_read_protocol(db, user, protocol_id)
    try:
        result = await service.export_standalone_pdf(db, protocol_id, template_id, "todos", body.filter)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (SQLAlchemyError, RuntimeError) as exc:
        db.rollback()
        record_system_error(db, exc=exc, request=request, tenant_id=user.current_tenant_id, actor_email=user.email, status_code=400)
        raise HTTPException(status_code=400, detail=_EXPORT_FAILED_MESSAGE) from exc
    audit.log(db, action="export.protocol_todo_list", actor=user, entity_type="protocol", entity_id=protocol_id)
    return result


@router.post("/protocols/{protocol_id}/exports/event-list", response_model=ProtocolExportRead)
async def export_event_list(
    protocol_id: uuid.UUID,
    body: StandaloneExportRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_reader(user)
    protocol_id = _resolve(db, Protocol, protocol_id, user, label="Protocol")
    template_id = _resolve(db, Template, body.template_id, user, label="Template")
    access_service.ensure_can_read_protocol(db, user, protocol_id)
    try:
        result = await service.export_standalone_pdf(db, protocol_id, template_id, "events", body.filter)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (SQLAlchemyError, RuntimeError) as exc:
        db.rollback()
        record_system_error(db, exc=exc, request=request, tenant_id=user.current_tenant_id, actor_email=user.email, status_code=400)
        raise HTTPException(status_code=400, detail=_EXPORT_FAILED_MESSAGE) from exc
    audit.log(db, action="export.protocol_event_list", actor=user, entity_type="protocol", entity_id=protocol_id)
    return result


@router.post("/exports/todos", response_model=ProtocolExportRead)
async def export_global_todos(
    body: GlobalTodoExportRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_reader(user)
    template_id = _resolve(db, Template, body.template_id, user, label="Template")
    participant_id = _resolve(db, Participant, body.participant_id, user, label="Participant") if body.participant_id else None
    try:
        result = await service.export_global_pdf(
            db, user.current_tenant_id, template_id, "todos", body.filter,
            participant_id=participant_id, group_by_person=body.group_by_person,
            until_date=body.until_date,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (SQLAlchemyError, RuntimeError) as exc:
        db.rollback()
        record_system_error(db, exc=exc, request=request, tenant_id=user.current_tenant_id, actor_email=user.email, status_code=400)
        raise HTTPException(status_code=400, detail=_EXPORT_FAILED_MESSAGE) from exc
    audit.log(db, action="export.global_todos", actor=user, details={"template_id": str(body.template_id)})
    return result


@router.post("/exports/todos/markdown", response_model=MarkdownExportRead)
async def export_global_todos_markdown(
    body: GlobalTodoMarkdownExportRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_reader(user)
    participant_id = _resolve(db, Participant, body.participant_id, user, label="Participant") if body.participant_id else None
    try:
        content = service.export_global_todo_markdown(
            db,
            user.current_tenant_id,
            body.filter,
            participant_id=participant_id,
            group_by_person=body.group_by_person,
            until_date=body.until_date,
            date_summary=body.date_summary,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (SQLAlchemyError, RuntimeError) as exc:
        db.rollback()
        record_system_error(db, exc=exc, request=request, tenant_id=user.current_tenant_id, actor_email=user.email, status_code=400)
        raise HTTPException(status_code=400, detail=_EXPORT_FAILED_MESSAGE) from exc
    audit.log(
        db,
        action="export.global_todos_markdown",
        actor=user,
        details={
            "filter": body.filter,
            "participant_id": str(body.participant_id) if body.participant_id else None,
            "group_by_person": body.group_by_person,
            "until_date": body.until_date,
            "date_summary": body.date_summary,
        },
    )
    return MarkdownExportRead(content=content)


@router.post("/exports/lists", response_model=ProtocolExportRead)
async def export_global_list(
    body: GlobalListExportRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_reader(user)
    template_id = _resolve(db, Template, body.template_id, user, label="Template")
    list_definition_id = _resolve(db, ListDefinition, body.list_definition_id, user, label="List")
    filter_participant_id = (
        _resolve(db, Participant, body.filter_participant_id, user, label="Participant") if body.filter_participant_id else None
    )
    filter_event_id = _resolve(db, Event, body.filter_event_id, user, label="Event") if body.filter_event_id else None
    try:
        result = await service.export_global_pdf(
            db, user.current_tenant_id, template_id, "list",
            list_definition_id=list_definition_id,
            list_group_by=body.group_by,
            list_sort_by=body.sort_by,
            list_sort_direction=body.sort_direction,
            list_filter_column=body.filter_column,
            list_filter_participant_id=filter_participant_id,
            list_filter_event_id=filter_event_id,
            list_filter_text=body.filter_text,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (SQLAlchemyError, RuntimeError) as exc:
        db.rollback()
        record_system_error(db, exc=exc, request=request, tenant_id=user.current_tenant_id, actor_email=user.email, status_code=400)
        raise HTTPException(status_code=400, detail=_EXPORT_FAILED_MESSAGE) from exc
    audit.log(
        db, action="export.global_list", actor=user,
        details={"template_id": str(body.template_id), "list_definition_id": str(body.list_definition_id)},
    )
    return result


@router.post("/exports/events", response_model=ProtocolExportRead)
async def export_global_events(
    body: GlobalEventExportRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_reader(user)
    template_id = _resolve(db, Template, body.template_id, user, label="Template")
    try:
        result = await service.export_global_pdf(
            db, user.current_tenant_id, template_id, "events",
            tag_filters=body.tag_filters, until_date=body.until_date,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (SQLAlchemyError, RuntimeError) as exc:
        db.rollback()
        record_system_error(db, exc=exc, request=request, tenant_id=user.current_tenant_id, actor_email=user.email, status_code=400)
        raise HTTPException(status_code=400, detail=_EXPORT_FAILED_MESSAGE) from exc
    audit.log(db, action="export.global_events", actor=user, details={"template_id": str(body.template_id)})
    return result
