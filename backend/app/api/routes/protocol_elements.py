import json

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, HTTPException

from app.core.db import get_db
from app.core.redis_client import get_redis_sync
from app.core.security import CurrentUser, get_current_user, require_reader, require_writer
from app.models import ProtocolElementBlock
from app.schemas.protocol import (
    ProtocolElementBlockFromEventCreate,
    ProtocolElementBlockRead,
    ProtocolElementBlockUpdate,
    ProtocolElementRead,
    ProtocolElementUpdate,
    ProtocolTextRead,
    ProtocolTextUpdate,
)
from app.services import list_snapshot_service
from app.services.autosave_service import AutosaveService
from app.services.access_service import AccessService
from app.services.collaboration_service import conflicting_lock_holder_sync, protocol_channel
from app.services.protocol_element_service import ProtocolElementService
from app.services.protocol_service import ProtocolService
from app.services.responsible_label_service import resolve_display_section_title

router = APIRouter()
autosave_service = AutosaveService()
service = ProtocolElementService()
protocol_service = ProtocolService()
access_service = AccessService()


def _broadcast_block_update(protocol_id: int, block: ProtocolElementBlock, user: CurrentUser) -> None:
    """Same mechanism regular block edits already use (collaboration_ws.py's field_update
    passthrough) - other viewers of this same protocol see the refresh/sync/undo live with
    no new frontend WS handling needed."""
    get_redis_sync().publish(
        protocol_channel(protocol_id),
        json.dumps({
            "type": "field_update",
            "field_key": f"block-{block.id}",
            "patch": {"configuration_snapshot_json": block.configuration_snapshot_json},
            "user_id": user.user_id,
            "display_name": user.display_name,
        }),
    )


def _block_and_protocol_or_404(db: Session, user: CurrentUser, protocol_element_block_id: int):
    """Shared guard for the list-snapshot/text/config routes below: resolves the block + its
    protocol, 404s if either is missing/inaccessible, 409s if the protocol is already
    abgeschlossen (permanently frozen, edits/refresh/undo no longer apply). The 404/409
    protocol check itself lives on ProtocolService so app/api/routes/todos.py can share the
    exact same logic for todos, which hang off a protocol_id rather than a block."""
    access_service.ensure_can_read_protocol_block(db, user, protocol_element_block_id)
    block = db.get(ProtocolElementBlock, protocol_element_block_id)
    if block is None:
        raise HTTPException(status_code=404, detail="Protocol element block not found")
    protocol_id = access_service.repository.protocol_id_for_block(db, protocol_element_block_id=protocol_element_block_id)
    protocol = protocol_service.get_protocol_or_404_not_frozen(db, protocol_id)
    return block, protocol


def _ensure_block_not_locked_by_other(protocol_id: int, protocol_element_block_id: int, user: CurrentUser) -> None:
    """The collaboration WS layer's Redis field lock (field_key `block-<id>`, same format
    collaboration_ws.py's field_update handler now itself enforces before broadcasting) used
    to be purely cosmetic here - a client that skipped the WS lock entirely (or never opened
    it at all) could still PATCH/PUT straight through with no server-side check. This closes
    that gap for the two endpoints that do the actual field write (config PATCH, text PUT):
    reject with 409 only if a *different* user demonstrably holds the lock right now. A write
    proceeds normally when nobody holds it - most writes never acquire a lock at all (matrix
    row/column edits, attendance batch edits, anything outside the click-to-edit text/config
    fields) and must keep working - or when the caller itself is the holder."""
    holder = conflicting_lock_holder_sync(
        get_redis_sync(), protocol_id, f"block-{protocol_element_block_id}", user.user_id
    )
    if holder is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Wird gerade von {holder.get('display_name', 'einer anderen Person')} bearbeitet",
        )


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
    access_service.ensure_can_read_protocol_element(db, user, protocol_element_id)
    protocol_id = access_service.repository.protocol_id_for_element(db, protocol_element_id=protocol_element_id)
    protocol_service.get_protocol_or_404_not_frozen(db, protocol_id)
    try:
        protocol_element = service.update_protocol_element(db, protocol_element_id, payload)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Protocol element could not be updated") from exc
    if protocol_element is None:
        raise HTTPException(status_code=404, detail="Protocol element not found")
    protocol = protocol_service.get_protocol(db, protocol_element.protocol_id)
    return ProtocolElementRead(
        id=protocol_element.id,
        protocol_id=protocol_element.protocol_id,
        template_element_id=protocol_element.template_element_id,
        sort_index=protocol_element.sort_index,
        section_name_snapshot=resolve_display_section_title(db, protocol_element, protocol.status if protocol else "", protocol.tenant_id if protocol else None),
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
    _, protocol = _block_and_protocol_or_404(db, user, protocol_element_block_id)
    _ensure_block_not_locked_by_other(protocol.id, protocol_element_block_id, user)
    try:
        protocol_element_block = service.update_protocol_element_block(db, protocol_element_block_id, payload)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Protocol element block could not be updated") from exc
    if protocol_element_block is None:
        raise HTTPException(status_code=404, detail="Protocol element block not found")
    return _block_to_read(protocol_element_block)


@router.post("/protocol-element-blocks/{protocol_element_block_id}/list-snapshot/refresh", response_model=ProtocolElementBlockRead)
def refresh_block_list_snapshot(
    protocol_element_block_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """User-initiated refresh: pulls in the list's current data, stashes the block's
    previous snapshot as the one undo step."""
    require_writer(user)
    block, protocol = _block_and_protocol_or_404(db, user, protocol_element_block_id)
    track_changes_active = protocol.status == "geplant" and protocol.track_changes_enabled
    block = list_snapshot_service.refresh_block_list_snapshot(
        db, block, protocol.tenant_id, keep_undo=True, track_changes_active=track_changes_active
    )
    _broadcast_block_update(protocol.id, block, user)
    return _block_to_read(block)


@router.post("/protocol-element-blocks/{protocol_element_block_id}/list-snapshot/sync", response_model=ProtocolElementBlockRead)
def sync_block_list_snapshot(
    protocol_element_block_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Silent resync called by the frontend right after the protocol itself writes to a
    linked list entry, so the editor never shows a stale hint for a change it just made
    itself. Never touches an existing undo point."""
    require_writer(user)
    block, protocol = _block_and_protocol_or_404(db, user, protocol_element_block_id)
    track_changes_active = protocol.status == "geplant" and protocol.track_changes_enabled
    block = list_snapshot_service.refresh_block_list_snapshot(
        db, block, protocol.tenant_id, keep_undo=False, track_changes_active=track_changes_active
    )
    _broadcast_block_update(protocol.id, block, user)
    return _block_to_read(block)


@router.post("/protocol-element-blocks/{protocol_element_block_id}/list-snapshot/undo", response_model=ProtocolElementBlockRead)
def undo_block_list_snapshot(
    protocol_element_block_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    block, protocol = _block_and_protocol_or_404(db, user, protocol_element_block_id)
    updated = list_snapshot_service.undo_block_list_snapshot(db, block)
    if updated is None:
        raise HTTPException(status_code=409, detail="Nothing to undo")
    _broadcast_block_update(protocol.id, updated, user)
    return _block_to_read(updated)


@router.delete("/protocol-element-blocks/{protocol_element_block_id}", status_code=204)
def delete_protocol_element_block(
    protocol_element_block_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    _block_and_protocol_or_404(db, user, protocol_element_block_id)
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
    access_service.ensure_can_read_protocol_element(db, user, protocol_element_id)
    protocol_id = access_service.repository.protocol_id_for_element(db, protocol_element_id=protocol_element_id)
    protocol_service.get_protocol_or_404_not_frozen(db, protocol_id)
    try:
        protocol_block = protocol_service.add_event_block_to_element(
            db,
            protocol_element_id=protocol_element_id,
            event_id=payload.event_id,
            tenant_id=user.current_tenant_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Block could not be created") from exc
    return _block_to_read(protocol_block)


@router.post("/protocol-element-blocks/{protocol_element_block_id}/list-snapshot/entries/{entry_id}/accept-tracked-change", response_model=ProtocolElementBlockRead)
def accept_tracked_list_entry(
    protocol_element_block_id: int,
    entry_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """'Ausblenden' for one whole-list entry's red tracked-change highlight."""
    require_writer(user)
    block, protocol = _block_and_protocol_or_404(db, user, protocol_element_block_id)
    block = list_snapshot_service.accept_tracked_list_entry(db, block, entry_id)
    _broadcast_block_update(protocol.id, block, user)
    return _block_to_read(block)


@router.post("/protocol-element-blocks/{protocol_element_block_id}/rows/{row_id}/accept-tracked-change", response_model=ProtocolElementBlockRead)
def accept_tracked_row(
    protocol_element_block_id: int,
    row_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """'Ausblenden' for one row-link ('Zeile aus Liste') form row's red tracked-change highlight."""
    require_writer(user)
    block, protocol = _block_and_protocol_or_404(db, user, protocol_element_block_id)
    block = list_snapshot_service.accept_tracked_row(db, block, row_id)
    _broadcast_block_update(protocol.id, block, user)
    return _block_to_read(block)


@router.post("/protocol-element-blocks/{protocol_element_block_id}/text/accept-tracked-changes", response_model=ProtocolTextRead)
def accept_text_tracked_changes(
    protocol_element_block_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """'Ausblenden' for a text block's red tracked-change highlight (whole block)."""
    require_writer(user)
    _block_and_protocol_or_404(db, user, protocol_element_block_id)
    try:
        result = autosave_service.accept_tracked_changes(db, protocol_element_block_id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Change could not be accepted") from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Text block not found")
    return ProtocolTextRead(**result)


@router.put("/protocol-element-blocks/{protocol_element_block_id}/text", response_model=ProtocolTextRead)
def put_protocol_text(
    protocol_element_block_id: int,
    payload: ProtocolTextUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    block, protocol = _block_and_protocol_or_404(db, user, protocol_element_block_id)
    _ensure_block_not_locked_by_other(protocol.id, protocol_element_block_id, user)
    track_changes_active = bool(protocol.status == "geplant" and protocol.track_changes_enabled)
    try:
        result = autosave_service.save_text_block(
            db,
            protocol_element_block_id,
            payload.content,
            tenant_id=protocol.tenant_id,
            track_changes_active=track_changes_active,
            block_config=block.configuration_snapshot_json,
        )
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Text block could not be saved") from exc
    return ProtocolTextRead(**result)
