from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, HTTPException

from app.core.db import get_db
from app.core.security import CurrentUser, get_current_user, require_editor
from app.schemas.protocol import ProtocolElementRead, ProtocolElementUpdate, ProtocolTextRead, ProtocolTextUpdate
from app.services.autosave_service import AutosaveService
from app.services.protocol_element_service import ProtocolElementService

router = APIRouter()
autosave_service = AutosaveService()
service = ProtocolElementService()


@router.get("/protocols/{protocol_id}/elements", response_model=list[ProtocolElementRead])
def list_protocol_elements(protocol_id: int, db: Session = Depends(get_db)):
    return service.list_protocol_elements(db, protocol_id)


@router.patch("/protocol-elements/{protocol_element_id}", response_model=ProtocolElementRead)
def patch_protocol_element(
    protocol_element_id: int,
    payload: ProtocolElementUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_editor(user)
    try:
        protocol_element = service.update_protocol_element(db, protocol_element_id, payload)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Protocol element could not be updated") from exc
    if protocol_element is None:
        raise HTTPException(status_code=404, detail="Protocol element not found")
    return ProtocolElementRead(
        **protocol_element.__dict__,
        element_type_code=None,
        render_type_code=None,
        text_content=None,
        display_compiled_text=None,
        display_snapshot_json={},
    )


@router.put("/protocol-elements/{protocol_element_id}/text", response_model=ProtocolTextRead)
def put_protocol_text(
    protocol_element_id: int,
    payload: ProtocolTextUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_editor(user)
    try:
        result = autosave_service.save_text_block(db, protocol_element_id, payload.content)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Text block could not be saved") from exc
    return ProtocolTextRead(**result)
