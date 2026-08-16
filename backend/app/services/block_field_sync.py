from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Event, Protocol, ProtocolElement, ProtocolElementBlock, ProtocolTodo

SYNC_TARGET_FIELDS: dict[str, tuple[str, ...]] = {
    "event": ("description", "location", "spezial_text1", "spezial_text2", "spezial_text3"),
    "todo": ("task", "reference_link", "due_marker"),
}


def _todo_tenant_id(db: Session, todo: ProtocolTodo) -> int | None:
    """ProtocolTodo.tenant_id is only populated for standalone todos (see
    create_standalone_todo) - a block-attached todo's tenant has to be resolved through its
    block's protocol instead."""
    if todo.tenant_id is not None:
        return todo.tenant_id
    if todo.protocol_element_block_id is None:
        return None
    return db.scalar(
        select(Protocol.tenant_id)
        .join(ProtocolElement, ProtocolElement.protocol_id == Protocol.id)
        .join(ProtocolElementBlock, ProtocolElementBlock.protocol_element_id == ProtocolElement.id)
        .where(ProtocolElementBlock.id == todo.protocol_element_block_id)
    )


def apply_text_sync(
    db: Session,
    *,
    tenant_id: int,
    repeat_source_type: str | None,
    repeat_source_id: int | None,
    sync_target_field: str | None,
    content: str,
) -> None:
    """Writes a "Pro Termin"/"Pro Todo" block's text content into the configured field of
    its linked Event/ProtocolTodo row. No-op unless a repeat source, target row and an
    allowlisted field for that source type are all present - protects against writing an
    arbitrary column if template configuration ever drifts (e.g. repeat_source switched
    away from event/todo after sync_target_field was already set).

    Also requires repeat_source_id to resolve to a row belonging to tenant_id (audit S9,
    2026-08-16): repeat_source_id comes from a block's configuration_snapshot_json, which a
    PATCH on the block can set freely - without this check, a cross-tenant repeat_source_id
    would write this block's text straight into a foreign tenant's Event/ProtocolTodo row.
    Not currently reachable end-to-end (both call sites already tenant-check upstream of
    here, see their own comments) - this closes the gap in the shared function itself so a
    future caller can't reintroduce it by skipping that upstream check."""
    if not sync_target_field or repeat_source_id is None or repeat_source_type not in SYNC_TARGET_FIELDS:
        return
    if sync_target_field not in SYNC_TARGET_FIELDS[repeat_source_type]:
        return
    model = Event if repeat_source_type == "event" else ProtocolTodo
    row = db.get(model, repeat_source_id)
    if row is None:
        return
    row_tenant_id = row.tenant_id if repeat_source_type == "event" else _todo_tenant_id(db, row)
    if row_tenant_id != tenant_id:
        return
    setattr(row, sync_target_field, content)
    db.add(row)
