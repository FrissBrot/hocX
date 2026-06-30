from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, HTTPException

from app.core.db import get_db
from app.core.security import CurrentUser, get_current_user, require_reader, require_writer
from app.schemas.protocol import (
    ProtocolElementBlockFromEventCreate,
    ProtocolElementBlockRead,
    ProtocolElementBlockUpdate,
    ProtocolElementRead,
    ProtocolElementUpdate,
    ProtocolTextRead,
    ProtocolTextUpdate,
)
from app.services.autosave_service import AutosaveService
from app.services.access_service import AccessService
from app.services.protocol_element_service import ProtocolElementService
from app.services.protocol_service import ProtocolService

router = APIRouter()
autosave_service = AutosaveService()
service = ProtocolElementService()
protocol_service = ProtocolService()
access_service = AccessService()


def _block_to_read(block) -> ProtocolElementBlockRead:
    return ProtocolElementBlockRead(
        id=block.id,
        protocol_element_id=block.protocol_element_id,
        template_element_block_id=block.template_element_block_id,
        element_definition_id=block.element_definition_id,
        element_type_id=block.element_type_id,
        render_type_id=block.render_type_id,
        element_type_code=None,
        render_type_code=None,
        title_snapshot=block.title_snapshot,
        display_title_snapshot=block.display_title_snapshot,
        description_snapshot=block.description_snapshot,
        block_title_snapshot=block.block_title_snapshot,
        is_editable_snapshot=block.is_editable_snapshot,
        allows_multiple_values_snapshot=block.allows_multiple_values_snapshot,
        sort_index=block.sort_index,
        render_order=block.render_order,
        is_required_snapshot=block.is_required_snapshot,
        is_visible_snapshot=block.is_visible_snapshot,
        export_visible_snapshot=block.export_visible_snapshot,
        latex_template_snapshot=block.latex_template_snapshot,
        configuration_snapshot_json=block.configuration_snapshot_json or {},
        text_content=None,
        display_compiled_text=None,
        display_snapshot_json={},
    )


@router.get("/protocols/{protocol_id}/elements", response_model=list[ProtocolElementRead])
def list_protocol_elements(
    protocol_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_reader(user)
    access_service.ensure_can_read_protocol(db, user, protocol_id)
    return service.list_protocol_elements(db, protocol_id)


@router.patch("/protocol-elements/{protocol_element_id}", response_model=ProtocolElementRead)
def patch_protocol_element(
    protocol_element_id: int,
    payload: ProtocolElementUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    try:
        protocol_element = service.update_protocol_element(db, protocol_element_id, payload)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Protocol element could not be updated") from exc
    if protocol_element is None:
        raise HTTPException(status_code=404, detail="Protocol element not found")
    return ProtocolElementRead(
        id=protocol_element.id,
        protocol_id=protocol_element.protocol_id,
        template_element_id=protocol_element.template_element_id,
        sort_index=protocol_element.sort_index,
        section_name_snapshot=protocol_element.section_name_snapshot,
        section_order_snapshot=protocol_element.section_order_snapshot,
        is_required_snapshot=protocol_element.is_required_snapshot,
        is_visible_snapshot=protocol_element.is_visible_snapshot,
        export_visible_snapshot=protocol_element.export_visible_snapshot,
        blocks=[],
    )


@router.patch("/protocol-element-blocks/{protocol_element_block_id}", response_model=ProtocolElementBlockRead)
def patch_protocol_element_block(
    protocol_element_block_id: int,
    payload: ProtocolElementBlockUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    try:
        protocol_element_block = service.update_protocol_element_block(db, protocol_element_block_id, payload)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Protocol element block could not be updated") from exc
    if protocol_element_block is None:
        raise HTTPException(status_code=404, detail="Protocol element block not found")
    return _block_to_read(protocol_element_block)


@router.delete("/protocol-element-blocks/{protocol_element_block_id}", status_code=204)
def delete_protocol_element_block(
    protocol_element_block_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    try:
        found = service.delete_protocol_element_block(db, protocol_element_block_id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Protocol element block could not be deleted") from exc
    if not found:
        raise HTTPException(status_code=404, detail="Protocol element block not found")


@router.post("/protocol-elements/{protocol_element_id}/blocks/from-event", response_model=ProtocolElementBlockRead)
def create_protocol_element_block_from_event(
    protocol_element_id: int,
    payload: ProtocolElementBlockFromEventCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    try:
        protocol_block = protocol_service.add_event_block_to_element(
            db,
            protocol_element_id=protocol_element_id,
            event_id=payload.event_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Block could not be created") from exc
    return _block_to_read(protocol_block)


@router.put("/protocol-element-blocks/{protocol_element_block_id}/text", response_model=ProtocolTextRead)
def put_protocol_text(
    protocol_element_block_id: int,
    payload: ProtocolTextUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    try:
        result = autosave_service.save_text_block(db, protocol_element_block_id, payload.content)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Text block could not be saved") from exc
    return ProtocolTextRead(**result)
