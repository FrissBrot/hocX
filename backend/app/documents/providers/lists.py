"""Strukturierte Listen und Formularwerte (Personen, Termine, Text) - Logik aus dem früheren
Export übernommen: gleiche Filter, Sortierung, Gruppierung und Mandantenprüfungen wie im Editor
(structured-list-table.tsx). Referenzen aus ``configuration_snapshot_json`` sind
benutzerkontrolliert und werden immer mandantengebunden aufgelöst (Audit 2026-08-25)."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.documents.catalog import BlockSpec, ListTableParams
from app.documents.context import BuildContext, format_date_range
from app.documents.model import Cell, ListTableBlock, TableColumn, TableData, TableGroup, TableRow
from app.documents.providers.common import inline_text, sort_key, spec_fields, text_cell
from app.models import Event, ListDefinition, ListEntry, Participant


def form_row_value(ctx: BuildContext, row: dict) -> str:
    value_type = row.get("value_type") or row.get("row_type") or "text"
    if value_type == "participant" and row.get("participant_id"):
        participant = ctx.entity_by_ref(Participant, row["participant_id"])
        return participant.display_name if participant else ""
    if value_type == "participants" and row.get("participant_ids"):
        participants = [ctx.entity_by_ref(Participant, ref) for ref in row.get("participant_ids", [])]
        return ", ".join(participant.display_name for participant in participants if participant)
    if value_type == "event" and row.get("event_id"):
        event = ctx.entity_by_ref(Event, row["event_id"])
        if not event:
            return ""
        return f"{format_date_range(event.event_date, event.event_end_date)} – {event.title}"
    return str(row.get("text_value") or "").strip()


def _column_meta(definition: Any, column_key: str) -> tuple[str, str]:
    if column_key == "column_two":
        return definition.column_two_title, definition.column_two_value_type
    return definition.column_one_title, definition.column_one_value_type


def _entry_value(entry: Any, column_key: str) -> dict:
    return dict((entry.column_two_value_json if column_key == "column_two" else entry.column_one_value_json) or {})


def _list_value(ctx: BuildContext, value_type: str, value: dict) -> str:
    return form_row_value(ctx, {"value_type": value_type, **(value or {})})


def _sort_text(ctx: BuildContext, value_type: str, value: dict) -> str:
    if value_type == "participant":
        participant = ctx.entity_by_ref(Participant, value.get("participant_id"))
        return str(participant.display_name if participant else "").strip()
    if value_type == "participants":
        participants = [p for p in (ctx.entity_by_ref(Participant, ref) for ref in (value.get("participant_ids") or [])) if p is not None]
        participants.sort(key=lambda participant: (participant.display_name.casefold(), participant.id))
        return ", ".join(participant.display_name for participant in participants)
    if value_type == "event":
        event = ctx.entity_by_ref(Event, value.get("event_id"))
        return str(event.title if event else "").strip()
    return str(value.get("text_value") or "").strip()


def form_row_list_entry(ctx: BuildContext, row: dict) -> tuple[str, str]:
    """Formularzeile vom Typ «Listeneintrag»: (Label, Wert)."""
    snapshot = row.get("list_snapshot")
    if isinstance(snapshot, dict):
        if not snapshot.get("entry_exists", True):
            return str(row.get("label") or "").strip(), ""
        definition = ListDefinition(
            column_one_title=snapshot.get("column_one_title") or "",
            column_one_value_type=snapshot.get("column_one_value_type") or "text",
            column_two_title=snapshot.get("column_two_title") or "",
            column_two_value_type=snapshot.get("column_two_value_type") or "text",
        )
        entry = ListEntry(column_one_value_json=snapshot.get("column_one_value") or {}, column_two_value_json=snapshot.get("column_two_value") or {})
    else:
        definition = ctx.entity_by_ref(ListDefinition, row.get("linked_list_id")) if row.get("linked_list_id") else None
        entry_id = ctx.ref_to_internal_id(ListEntry, row.get("linked_list_entry_id")) if row.get("linked_list_entry_id") else None
        entry = ctx.db.get(ListEntry, entry_id) if entry_id else None
        if definition is None or entry is None or entry.list_definition_id != definition.id:
            return str(row.get("label") or "").strip(), ""
    fixed = "column_two" if row.get("list_fixed_column") == "column_two" else "column_one"
    variable = "column_one" if fixed == "column_two" else "column_two"
    _, fixed_type = _column_meta(definition, fixed)
    _, variable_type = _column_meta(definition, variable)
    alias = str(row.get("label") or "").strip()
    label = alias or _list_value(ctx, fixed_type, _entry_value(entry, fixed))
    return label, _list_value(ctx, variable_type, _entry_value(entry, variable))


def list_table(ctx: BuildContext, list_definition_id: int | None, config: dict | None) -> TableData | None:
    """Liste als Tabelle; ``config`` im Format der Blockkonfiguration (linked_list_*), optional
    mit eingefrorenem ``list_snapshot`` eines Protokollblocks."""
    config = config if isinstance(config, dict) else {}
    snapshot = config.get("list_snapshot")
    if isinstance(snapshot, dict) and isinstance(snapshot.get("entries"), list):
        definition = ListDefinition(
            column_one_title=snapshot.get("column_one_title") or "",
            column_one_value_type=snapshot.get("column_one_value_type") or "text",
            column_two_title=snapshot.get("column_two_title") or "",
            column_two_value_type=snapshot.get("column_two_value_type") or "text",
        )
        entries = [
            ListEntry(id=item.get("id"), sort_index=item.get("sort_index") or 0, column_one_value_json=item.get("column_one_value") or {}, column_two_value_json=item.get("column_two_value") or {})
            for item in snapshot["entries"]
        ]
    else:
        definition = ctx.db.get(ListDefinition, list_definition_id) if list_definition_id else None
        if definition is None or definition.tenant_id != ctx.tenant_id:
            return None
        entries = list(ctx.db.scalars(select(ListEntry).where(ListEntry.list_definition_id == definition.id).order_by(ListEntry.sort_index.asc(), ListEntry.id.asc())))

    columns = [TableColumn(key="column_one", label=definition.column_one_title), TableColumn(key="column_two", label=definition.column_two_title)]

    filter_column = str(config.get("linked_list_filter_column") or "").strip()
    if filter_column in {"column_one", "column_two"}:
        _, filter_type = _column_meta(definition, filter_column)
        filter_participant = ctx.ref_to_internal_id(Participant, config.get("linked_list_filter_participant_id"))
        filter_event = ctx.ref_to_internal_id(Event, config.get("linked_list_filter_event_id"))
        filter_text = str(config.get("linked_list_filter_text") or "").strip().lower()

        def matches(entry: Any) -> bool:
            value = _entry_value(entry, filter_column)
            if filter_type == "participant" and filter_participant:
                return ctx.ref_to_internal_id(Participant, value.get("participant_id")) == filter_participant
            if filter_type == "participants" and filter_participant:
                return filter_participant in [ctx.ref_to_internal_id(Participant, ref) for ref in (value.get("participant_ids") or [])]
            if filter_type == "event" and filter_event:
                return ctx.ref_to_internal_id(Event, value.get("event_id")) == filter_event
            if filter_text:
                return filter_text in str(_list_value(ctx, filter_type, value) or "").lower()
            return True

        entries = [entry for entry in entries if matches(entry)]

    group_by = str(config.get("linked_list_group_by") or "")
    group_by = group_by if group_by in {"column_one", "column_two"} else ""
    sort_by = str(config.get("linked_list_sort_by") or "")
    sort_by = sort_by if sort_by in {"column_one", "column_two"} else ""
    descending = str(config.get("linked_list_sort_direction") or "").lower() == "desc"

    items: list[dict] = []
    for entry in entries:
        left = _list_value(ctx, definition.column_one_value_type, dict(entry.column_one_value_json or {}))
        right = _list_value(ctx, definition.column_two_value_type, dict(entry.column_two_value_json or {}))
        if not str(left).strip() and not str(right).strip():
            continue
        item = {"entry": entry, "left": left, "right": right, "sort": "", "group": None}
        if sort_by:
            _, sort_type = _column_meta(definition, sort_by)
            item["sort"] = sort_key(_sort_text(ctx, sort_type, _entry_value(entry, sort_by)))
        if group_by:
            _, group_type = _column_meta(definition, group_by)
            item["group"] = inline_text(_list_value(ctx, group_type, _entry_value(entry, group_by)))
        items.append(item)

    items.sort(key=lambda item: (item["entry"].sort_index or 0, item["entry"].id or 0))
    if sort_by:
        filled = sorted((item for item in items if item["sort"]), key=lambda item: item["sort"], reverse=descending)
        items = filled + [item for item in items if not item["sort"]]

    highlight_empty = bool(config.get("linked_list_highlight_empty", False))

    def cell(value: str) -> Cell:
        if not str(value or "").strip() and highlight_empty:
            return Cell(k="text", v="—", tone="warning")
        return text_cell(value)

    if not group_by:
        rows = [TableRow(cells=[cell(item["left"]), cell(item["right"])]) for item in items]
        return TableData(columns=columns, groups=[TableGroup(rows=rows)] if rows else [])

    # Gruppiert: eine Zeile pro Gruppenwert, die anderen Werte zusammengefasst (wie bisher).
    grouped: dict[str, dict] = {}
    for item in items:
        key = sort_key(item["group"]) or "__empty__"
        bucket = grouped.setdefault(key, {"label": item["group"], "left": [], "right": []})
        bucket["left"].append(inline_text(item["left"]))
        bucket["right"].append(inline_text(item["right"]))
    rows: list[TableRow] = []
    for bucket in grouped.values():
        merged_left = ", ".join(value for value in bucket["left"] if value)
        merged_right = ", ".join(value for value in bucket["right"] if value)
        label_cell = text_cell(bucket["label"]) if bucket["label"] else Cell(k="text", v="", note_key="group.noValue")
        if group_by == "column_one":
            rows.append(TableRow(cells=[label_cell, text_cell(merged_right)]))
        else:
            rows.append(TableRow(cells=[text_cell(merged_left), label_cell]))
    return TableData(columns=columns, groups=[TableGroup(rows=rows)] if rows else [])


def provide(ctx: BuildContext, spec: BlockSpec, params: ListTableParams):
    definition = ctx.require_entity(ListDefinition, params.list_id) if params.list_id else None
    config = {
        "linked_list_group_by": params.group_by,
        "linked_list_sort_by": params.sort_by,
        "linked_list_sort_direction": params.sort_direction,
        "linked_list_filter_column": params.filter_column,
        "linked_list_filter_participant_id": params.filter_participant_id,
        "linked_list_filter_event_id": params.filter_event_id,
        "linked_list_filter_text": params.filter_text,
        "linked_list_highlight_empty": params.highlight_empty,
    }
    table = list_table(ctx, definition.id if definition else None, config) if definition else None
    title = spec.title if spec.title is not None else (definition.name if definition else None)
    return [ListTableBlock(**spec_fields(spec, title=title), table=table or TableData(columns=[TableColumn(key="column_one")]))]
