from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.db import get_db
from app.schemas.protocol import ProtocolCreateFromTemplate, ProtocolRead, ProtocolUpdate
from app.services.protocol_service import ProtocolService

router = APIRouter()
service = ProtocolService()


@router.get("/protocols", response_model=list[ProtocolRead])
def list_protocols(db: Session = Depends(get_db)):
    return service.list_protocols(db)


@router.post("/protocols/from-template", response_model=dict[str, int], status_code=status.HTTP_201_CREATED)
def create_protocol_from_template(payload: ProtocolCreateFromTemplate, db: Session = Depends(get_db)):
    try:
        protocol_id = service.create_from_template(db, payload)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Protocol could not be created") from exc
    return {"id": protocol_id}


@router.get("/protocols/{protocol_id}", response_model=ProtocolRead)
def get_protocol(protocol_id: int, db: Session = Depends(get_db)):
    protocol = service.get_protocol(db, protocol_id)
    if protocol is None:
        raise HTTPException(status_code=404, detail="Protocol not found")
    return protocol


@router.patch("/protocols/{protocol_id}", response_model=ProtocolRead)
def patch_protocol(protocol_id: int, payload: ProtocolUpdate, db: Session = Depends(get_db)):
    try:
        protocol = service.update_protocol(db, protocol_id, payload)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Protocol could not be updated") from exc
    if protocol is None:
        raise HTTPException(status_code=404, detail="Protocol not found")
    return protocol
