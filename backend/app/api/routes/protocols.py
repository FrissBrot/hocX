from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.security import CurrentUser, get_current_user, require_reader, require_writer
from app.core.db import get_db
from app.schemas.protocol import ProtocolCreateFromTemplate, ProtocolRead, ProtocolUpdate
from app.services.protocol_service import ProtocolService

router = APIRouter()
service = ProtocolService()


@router.get("/protocols", response_model=list[ProtocolRead])
def list_protocols(
    q: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_reader(user)
    return service.list_protocols(db, tenant_id=user.current_tenant_id, query=q, status=status_filter)


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
    return protocol


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
