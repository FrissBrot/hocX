from __future__ import annotations

from typing import Any

from sqlalchemy import select
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


def _resolve_ids_for_assignments(
    assignments: list[dict[str, Any]] | None,
    *,
    live: bool,
    db: Session | None,
    entries_by_id: dict[int, ListEntry] | None = None,
    definitions_by_id: dict[int, ListDefinition] | None = None,
) -> list[int]:
    """Resolves the deduplicated, order-preserving list of participant ids referenced by
    `assignments`, following the same list-entry/list-definition/participant_id fallback as
    resolve_responsible_label(). When `entries_by_id`/`definitions_by_id` are given (batch
    path), list rows are looked up there instead of issuing a `db.get()` per assignment."""
    resolved_ids: list[int] = []
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
        ids = [participant_id] if participant_id else []
        if live and list_definition_id and list_entry_id:
            if entries_by_id is not None:
                entry = entries_by_id.get(int(list_entry_id))
            else:
                entry = db.get(ListEntry, int(list_entry_id)) if db is not None else None
            if definitions_by_id is not None:
                definition = definitions_by_id.get(int(list_definition_id))
            else:
                definition = db.get(ListDefinition, int(list_definition_id)) if db is not None else None
            if entry is not None and definition is not None:
                ids = _list_entry_participant_ids(entry, definition)
        for pid in ids:
            if not pid or pid in seen_ids:
                continue
            seen_ids.add(pid)
            resolved_ids.append(pid)
    return resolved_ids


def resolve_responsible_label(
    db: Session,
    assignments: list[dict[str, Any]] | None,
    name_display_mode: str | None,
    *,
    live: bool,
    tenant_id: int | None,
    entries_by_id: dict[int, ListEntry] | None = None,
    definitions_by_id: dict[int, ListDefinition] | None = None,
    participants_by_id: dict[int, Participant] | None = None,
) -> str:
    mode = name_display_mode or "display_name"
    resolved_ids = _resolve_ids_for_assignments(
        assignments,
        live=live,
        db=db,
        entries_by_id=entries_by_id,
        definitions_by_id=definitions_by_id,
    )
    names: list[str] = []
    for pid in resolved_ids:
        participant = participants_by_id.get(pid) if participants_by_id is not None else db.get(Participant, pid)
        # resolved_ids can come from a directly-embedded assignment.participant_id or from a
        # list entry's stored value (list_service._normalize_value tenant-checks new writes,
        # but pre-existing rows/legacy config could still hold a foreign id) - never resolve
        # and display a participant belonging to a different tenant (audit finding H1,
        # 2026-08-25).
        if participant is not None and participant.tenant_id != tenant_id:
            participant = None
        name = _responsible_participant_name(participant, mode=mode, fallback_id=pid)
        if name:
            names.append(name)
    return ", ".join(names)


def resolve_responsible_labels_batch(db: Session, elements: list[ProtocolElement], tenant_id: int | None) -> dict[int, str]:
    """Batch equivalent of calling resolve_responsible_label(..., live=True) once per element:
    collects every list_entry_id/list_definition_id/participant_id referenced across all
    elements' responsible_assignments_snapshot up front and loads ListEntry/ListDefinition/
    Participant with one IN(...) query per table, instead of the per-element (and
    per-assignment) db.get() calls the single-element path would otherwise issue. Unlike
    resolve_display_section_titles_batch(), this always resolves live (no protocol_status
    gate) and returns the bare label rather than "title (label)" - used by
    protocol_service._freeze_responsible_titles(), which builds its own snapshot string."""
    list_entry_ids: set[int] = set()
    list_definition_ids: set[int] = set()
    for element in elements:
        for assignment in element.responsible_assignments_snapshot or []:
            if not isinstance(assignment, dict):
                continue
            list_entry_id = assignment.get("list_entry_id")
            list_definition_id = assignment.get("list_definition_id")
            if list_entry_id:
                try:
                    list_entry_ids.add(int(list_entry_id))
                except (TypeError, ValueError):
                    pass
            if list_definition_id:
                try:
                    list_definition_ids.add(int(list_definition_id))
                except (TypeError, ValueError):
                    pass

    entries_by_id: dict[int, ListEntry] = (
        {row.id: row for row in db.scalars(select(ListEntry).where(ListEntry.id.in_(list_entry_ids)))}
        if list_entry_ids
        else {}
    )
    definitions_by_id: dict[int, ListDefinition] = (
        {row.id: row for row in db.scalars(select(ListDefinition).where(ListDefinition.id.in_(list_definition_ids)))}
        if list_definition_ids
        else {}
    )

    resolved_ids_by_element_id: dict[int, list[int]] = {
        element.id: _resolve_ids_for_assignments(
            element.responsible_assignments_snapshot,
            live=True,
            db=None,
            entries_by_id=entries_by_id,
            definitions_by_id=definitions_by_id,
        )
        for element in elements
    }
    participant_ids = {pid for ids in resolved_ids_by_element_id.values() for pid in ids}
    # Scoped to tenant_id at the query itself, not just filtered afterwards - a resolved id
    # from a directly-embedded assignment.participant_id or a legacy/pre-fix list entry
    # value could belong to a different tenant, and must never resolve to a real name here
    # (audit finding H1, 2026-08-25).
    participants_by_id: dict[int, Participant] = (
        {
            row.id: row
            for row in db.scalars(
                select(Participant).where(Participant.id.in_(participant_ids), Participant.tenant_id == tenant_id)
            )
        }
        if participant_ids
        else {}
    )

    labels_by_element_id: dict[int, str] = {}
    for element in elements:
        mode = element.responsible_name_display_mode or "display_name"
        names: list[str] = []
        for pid in resolved_ids_by_element_id.get(element.id, []):
            participant = participants_by_id.get(pid)
            name = _responsible_participant_name(participant, mode=mode, fallback_id=pid)
            if name:
                names.append(name)
        labels_by_element_id[element.id] = ", ".join(names)
    return labels_by_element_id


def resolve_display_section_title(db: Session, element: ProtocolElement, protocol_status: str, tenant_id: int | None) -> str:
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
            tenant_id=tenant_id,
        )
        return f"{element.element_title_snapshot} ({label})" if label else element.element_title_snapshot
    return element.section_name_snapshot


def resolve_display_section_titles_batch(
    db: Session, elements: list[ProtocolElement], protocol_status: str, tenant_id: int | None
) -> dict[int, str]:
    """Batch equivalent of calling resolve_display_section_title() once per element: collects
    every list_entry_id/list_definition_id/participant_id referenced across all elements'
    responsible_assignments_snapshot up front and loads ListEntry/ListDefinition/Participant
    with one IN(...) query per table, instead of the per-element (and per-assignment)
    db.get() calls the single-element path would otherwise issue. Returns exactly the same
    values resolve_display_section_title() would for each element, keyed by element.id."""
    live_elements = [
        element
        for element in elements
        if (
            protocol_status != "abgeschlossen"
            and element.element_title_snapshot
            and element.responsible_assignments_snapshot
        )
    ]
    live_element_ids = {element.id for element in live_elements}

    list_entry_ids: set[int] = set()
    list_definition_ids: set[int] = set()
    for element in live_elements:
        for assignment in element.responsible_assignments_snapshot or []:
            if not isinstance(assignment, dict):
                continue
            list_entry_id = assignment.get("list_entry_id")
            list_definition_id = assignment.get("list_definition_id")
            if list_entry_id:
                try:
                    list_entry_ids.add(int(list_entry_id))
                except (TypeError, ValueError):
                    pass
            if list_definition_id:
                try:
                    list_definition_ids.add(int(list_definition_id))
                except (TypeError, ValueError):
                    pass

    entries_by_id: dict[int, ListEntry] = (
        {row.id: row for row in db.scalars(select(ListEntry).where(ListEntry.id.in_(list_entry_ids)))}
        if list_entry_ids
        else {}
    )
    definitions_by_id: dict[int, ListDefinition] = (
        {row.id: row for row in db.scalars(select(ListDefinition).where(ListDefinition.id.in_(list_definition_ids)))}
        if list_definition_ids
        else {}
    )

    resolved_ids_by_element_id: dict[int, list[int]] = {
        element.id: _resolve_ids_for_assignments(
            element.responsible_assignments_snapshot,
            live=True,
            db=None,
            entries_by_id=entries_by_id,
            definitions_by_id=definitions_by_id,
        )
        for element in live_elements
    }
    participant_ids = {pid for ids in resolved_ids_by_element_id.values() for pid in ids}
    # See resolve_responsible_labels_batch's identical comment - scoped to tenant_id at the
    # query itself (audit finding H1, 2026-08-25).
    participants_by_id: dict[int, Participant] = (
        {
            row.id: row
            for row in db.scalars(
                select(Participant).where(Participant.id.in_(participant_ids), Participant.tenant_id == tenant_id)
            )
        }
        if participant_ids
        else {}
    )

    titles_by_element_id: dict[int, str] = {}
    for element in elements:
        if element.id not in live_element_ids:
            titles_by_element_id[element.id] = element.section_name_snapshot
            continue
        mode = element.responsible_name_display_mode or "display_name"
        names: list[str] = []
        for pid in resolved_ids_by_element_id.get(element.id, []):
            participant = participants_by_id.get(pid)
            name = _responsible_participant_name(participant, mode=mode, fallback_id=pid)
            if name:
                names.append(name)
        label = ", ".join(names)
        titles_by_element_id[element.id] = (
            f"{element.element_title_snapshot} ({label})" if label else element.element_title_snapshot
        )
    return titles_by_element_id
