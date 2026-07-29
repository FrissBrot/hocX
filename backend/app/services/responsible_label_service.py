from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import ListDefinition, ListEntry, Participant, ProtocolElement


def _responsible_participant_name(participant: Participant | None, *, mode: str, fallback_id: int | None = None) -> str:
    if participant is None:
        return f"Teilnehmer {fallback_id}" if fallback_id else ""
    if mode == "first_name":
        return (participant.first_name or "").strip() or participant.display_name
    if mode == "last_name":
        return (participant.last_name or "").strip() or participant.display_name
    return participant.display_name


def _list_entry_participant_ids(entry: ListEntry, definition: ListDefinition) -> list[int]:
    """Find whichever column of the list holds participant data and read its current
    value from the given entry. Mirrors eligibleResponsibleList()/listParticipantIds()
    in frontend/components/template/template-builder.tsx."""
    if definition.column_one_value_type in ("participant", "participants"):
        value = entry.column_one_value_json or {}
    elif definition.column_two_value_type in ("participant", "participants"):
        value = entry.column_two_value_json or {}
    else:
        return []
    participant_id = value.get("participant_id")
    if participant_id:
        return [int(participant_id)]
    participant_ids = value.get("participant_ids")
    if isinstance(participant_ids, list):
        return [int(pid) for pid in participant_ids if pid]
    return []


def resolve_responsible_label(
    db: Session,
    assignments: list[dict[str, Any]] | None,
    name_display_mode: str | None,
    *,
    live: bool,
) -> str:
    mode = name_display_mode or "display_name"
    names: list[str] = []
    seen_ids: set[int] = set()
    for assignment in assignments or []:
        if not isinstance(assignment, dict):
            continue
        try:
            participant_id = int(assignment.get("participant_id") or 0)
        except (TypeError, ValueError):
            participant_id = 0
        list_definition_id = assignment.get("list_definition_id")
        list_entry_id = assignment.get("list_entry_id")
        resolved_ids = [participant_id] if participant_id else []
        if live and list_definition_id and list_entry_id:
            entry = db.get(ListEntry, int(list_entry_id))
            definition = db.get(ListDefinition, int(list_definition_id))
            if entry is not None and definition is not None:
                resolved_ids = _list_entry_participant_ids(entry, definition)
        for pid in resolved_ids:
            if not pid or pid in seen_ids:
                continue
            seen_ids.add(pid)
            participant = db.get(Participant, pid)
            name = _responsible_participant_name(participant, mode=mode, fallback_id=pid)
            if name:
                names.append(name)
    return ", ".join(names)


def resolve_display_section_title(db: Session, element: ProtocolElement, protocol_status: str) -> str:
    """The title shown for a ProtocolElement: live-resolved from a linked list entry's
    current value while the protocol is not yet finalized, otherwise the frozen
    section_name_snapshot (also used for elements without any list-linked responsibility)."""
    if (
        protocol_status != "abgeschlossen"
        and element.element_title_snapshot
        and element.responsible_assignments_snapshot
    ):
        label = resolve_responsible_label(
            db,
            element.responsible_assignments_snapshot,
            element.responsible_name_display_mode,
            live=True,
        )
        return f"{element.element_title_snapshot} ({label})" if label else element.element_title_snapshot
    return element.section_name_snapshot
