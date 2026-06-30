from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.security import CurrentUser, get_current_user, require_reader, require_writer
from app.core.db import get_db
from app.schemas.protocol import ProtocolCreateFromTemplate, ProtocolRead, ProtocolTodoRead, ProtocolUpdate, QuickTodoCreate, TodoListItem
from app.services.access_service import AccessService
from app.services.audit_service import AuditService
from app.services.protocol_service import ProtocolService
from app.services.protocol_todo_service import ProtocolTodoService

router = APIRouter()
service = ProtocolService()
todo_service = ProtocolTodoService()
access_service = AccessService()
audit = AuditService()


@router.get("/protocols", response_model=list[ProtocolRead])
def list_protocols(
    q: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_reader(user)
    # Reader and kassier may only see finalized protocols
    if not user.is_superadmin and user.current_role in {"reader", "kassier"}:
        status_filter = "abgeschlossen"
        q = None  # no search for restricted roles
    return service.list_protocols(
        db,
        tenant_id=user.current_tenant_id,
        query=q,
        status=status_filter,
        user_id=user.user_id,
        restrict_to_assigned=access_service._is_restricted_reader(db, user),
        skip=skip,
        limit=limit,
    )


@router.post("/protocols/from-template", response_model=dict[str, int], status_code=status.HTTP_201_CREATED)
def create_protocol_from_template(
    payload: ProtocolCreateFromTemplate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    try:
        protocol_id = service.create_from_template(db, payload, tenant_id=user.current_tenant_id, created_by=user.user_id)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Protocol could not be created") from exc
    return {"id": protocol_id}


@router.get("/protocols/{protocol_id}", response_model=ProtocolRead)
def get_protocol(protocol_id: int, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_reader(user)
    protocol = service.get_protocol(db, protocol_id)
    if protocol is None or protocol.tenant_id != user.current_tenant_id:
        raise HTTPException(status_code=404, detail="Protocol not found")
    access_service.ensure_can_read_protocol(db, user, protocol_id)
    return protocol


@router.patch("/protocols/{protocol_id}", response_model=ProtocolRead)
def patch_protocol(
    protocol_id: int,
    payload: ProtocolUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    existing = service.get_protocol(db, protocol_id)
    if existing is None or existing.tenant_id != user.current_tenant_id:
        raise HTTPException(status_code=404, detail="Protocol not found")
    try:
        protocol = service.update_protocol(db, protocol_id, payload)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Protocol could not be updated") from exc
    if protocol is None:
        raise HTTPException(status_code=404, detail="Protocol not found")
    if payload.status is not None and payload.status != existing.status:
        audit.log(db, action="protocol.status_changed", actor=user, entity_type="protocol", entity_id=protocol_id,
                  details={"from": existing.status, "to": payload.status})
    return protocol


_PREVIOUS_STATUS: dict[str, str] = {
    "vorbereitet": "geplant",
    "durchgeführt": "vorbereitet",
    "abgeschlossen": "durchgeführt",
}


@router.post("/protocols/{protocol_id}/revert-status", response_model=ProtocolRead)
def revert_protocol_status(
    protocol_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    existing = service.get_protocol(db, protocol_id)
    if existing is None or existing.tenant_id != user.current_tenant_id:
        raise HTTPException(status_code=404, detail="Protocol not found")
    prev = _PREVIOUS_STATUS.get(existing.status)
    if prev is None:
        raise HTTPException(status_code=400, detail="Protocol is already at the initial status")
    try:
        protocol = service.update_protocol(db, protocol_id, ProtocolUpdate(status=prev))
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Status could not be reverted") from exc
    if protocol is None:
        raise HTTPException(status_code=404, detail="Protocol not found")
    audit.log(db, action="protocol.status_reverted", actor=user, entity_type="protocol", entity_id=protocol_id,
              details={"from": existing.status, "to": prev})
    return protocol


@router.get("/protocols/{protocol_id}/pending-todos", response_model=list[TodoListItem])
def get_pending_todos(
    protocol_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Open session todos from earlier protocols of the same template."""
    require_reader(user)
    protocol = service.get_protocol(db, protocol_id)
    if protocol is None or protocol.tenant_id != user.current_tenant_id:
        raise HTTPException(status_code=404, detail="Protocol not found")
    return todo_service.list_pending_for_protocol(
        db,
        protocol_id=protocol_id,
        template_id=protocol.template_id,
        protocol_date=protocol.protocol_date,
    )


@router.post("/protocols/{protocol_id}/quick-todos", response_model=dict, status_code=status.HTTP_201_CREATED)
def create_quick_todo(
    protocol_id: int,
    payload: QuickTodoCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Create a session todo, auto-creating the Sitzungsnotizen element+block if needed."""
    require_writer(user)
    existing = service.get_protocol(db, protocol_id)
    if existing is None or existing.tenant_id != user.current_tenant_id:
        raise HTTPException(status_code=404, detail="Protocol not found")
    try:
        block, todo = service.create_quick_todo(
            db,
            protocol_id=protocol_id,
            task=payload.task,
            tag=payload.tag,
            created_by=user.user_id,
        )
    except (ValueError, SQLAlchemyError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "block_id": block.id,
        "todo_id": todo.id,
        "element_id": block.protocol_element_id,
    }


@router.delete("/protocols/{protocol_id}", response_model=dict[str, str])
def delete_protocol(
    protocol_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    existing = service.get_protocol(db, protocol_id)
    if existing is None or existing.tenant_id != user.current_tenant_id:
        raise HTTPException(status_code=404, detail="Protocol not found")
    try:
        deleted = service.delete_protocol(db, protocol_id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Protocol could not be deleted") from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Protocol not found")
    return {"message": "Protocol deleted"}
