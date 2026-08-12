from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Event, ProtocolTodo

SYNC_TARGET_FIELDS: dict[str, tuple[str, ...]] = {
    "event": ("description", "location", "spezial_text1", "spezial_text2", "spezial_text3"),
    "todo": ("task", "reference_link", "due_marker"),
}


def apply_text_sync(
    db: Session,
    *,
    repeat_source_type: str | None,
    repeat_source_id: int | None,
    sync_target_field: str | None,
    content: str,
) -> None:
    """Writes a "Pro Termin"/"Pro Todo" block's text content into the configured field of
    its linked Event/ProtocolTodo row. No-op unless a repeat source, target row and an
    allowlisted field for that source type are all present - protects against writing an
    arbitrary column if template configuration ever drifts (e.g. repeat_source switched
    away from event/todo after sync_target_field was already set)."""
    if not sync_target_field or repeat_source_id is None or repeat_source_type not in SYNC_TARGET_FIELDS:
        return
    if sync_target_field not in SYNC_TARGET_FIELDS[repeat_source_type]:
        return
    model = Event if repeat_source_type == "event" else ProtocolTodo
    row = db.get(model, repeat_source_id)
    if row is None:
        return
    setattr(row, sync_target_field, content)
    db.add(row)
