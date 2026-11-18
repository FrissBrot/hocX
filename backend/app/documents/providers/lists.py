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
from app.services import list_columns, list_legacy_adapter


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


class _View:
    """Liste für die Ausgabe: Spalten (Key, Titel, Typ) und Einträge mit Werten je Key - aus der
    Live-Liste oder aus einem eingefrorenen Snapshot (v1 über den Adapter, siehe
    services/list_legacy_adapter.py)."""

    def __init__(self, columns: list[tuple[str, str, str]], entries: list[dict], label_key: str | None = None):
        self.columns = columns
        self.entries = entries
        self.types = {key: value_type for key, _title, value_type in columns}
        self.label_key = label_key if label_key in self.types else (columns[0][0] if columns else None)

    def has(self, key: str | None) -> bool:
        return bool(key) and key in self.types


def _live_view(definition: ListDefinition, entries: list[ListEntry]) -> _View:
    columns = [(column.key, column.title, column.value_type) for column in list_columns.columns_of(definition)]
    label = list_columns.label_column(definition)
    return _View(
        columns,
        [{"id": entry.id, "sort_index": entry.sort_index, "values": dict(entry.values_json or {})} for entry in entries],
        label.key if label else None,
    )


def _snapshot_view(snapshot: dict, definition: ListDefinition | None) -> _View:
    snapshot = list_legacy_adapter.upgrade_list_snapshot(snapshot, definition=definition)
    columns = [
        (str(column.get("id")), str(column.get("title") or ""), str(column.get("value_type") or "text"))
        for column in sorted(snapshot.get("columns") or [], key=lambda column: column.get("sort_index") or 0)
        if isinstance(column, dict)
    ]
    entries = [
        {"id": item.get("id"), "sort_index": item.get("sort_index") or 0, "values": dict(item.get("values") or {})}
        for item in (snapshot.get("entries") or []) if isinstance(item, dict)
    ]
    return _View(columns, entries, snapshot.get("label_column_id"))


def _resolve_key(view: _View, definition: ListDefinition | None, key: Any) -> str | None:
    """Spalten-Key aus einer Konfiguration in der Sicht: direkt, oder (alter Key) über die Liste."""
    if key in (None, ""):
        return None
    text_key = str(key)
    if view.has(text_key):
        return text_key
    column = list_columns.resolve_column(definition, text_key)
    if column is not None and view.has(column.key):
        return column.key
    synthetic = f"legacy:{text_key}" if list_legacy_adapter.is_legacy_key(text_key) else None
    return synthetic if synthetic and view.has(synthetic) else None


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
    """Formularzeile vom Typ «Listeneintrag»: (Label, Wert). Label aus der festen Spalte
    (``list_fixed_column``, sonst die Bezeichnungs-Spalte der Liste), Wert aus
    ``list_value_column`` (sonst die erste andere Spalte)."""
    live_definition = ctx.entity_by_ref(ListDefinition, row.get("linked_list_id")) if row.get("linked_list_id") else None
    snapshot = row.get("list_snapshot")
    if isinstance(snapshot, dict):
        if not snapshot.get("entry_exists", True):
            return str(row.get("label") or "").strip(), ""
        upgraded = list_legacy_adapter.upgrade_list_snapshot(snapshot, definition=live_definition)
        view = _snapshot_view({**upgraded, "entries": [{"id": 0, "values": upgraded.get("values") or {}}]}, live_definition)
    else:
        entry_id = ctx.ref_to_internal_id(ListEntry, row.get("linked_list_entry_id")) if row.get("linked_list_entry_id") else None
        entry = ctx.db.get(ListEntry, entry_id) if entry_id else None
        if live_definition is None or entry is None or entry.list_definition_id != live_definition.id:
            return str(row.get("label") or "").strip(), ""
        view = _live_view(live_definition, [entry])
    if not view.entries:
        return str(row.get("label") or "").strip(), ""
    values = view.entries[0]["values"]
    fixed = _resolve_key(view, live_definition, row.get("list_fixed_column")) or view.label_key
    variable = _resolve_key(view, live_definition, row.get("list_value_column"))
    if variable is None or variable == fixed:
        variable = next((key for key, _title, _type in view.columns if key != fixed), None)
    alias = str(row.get("label") or "").strip()
    label = alias or (_list_value(ctx, view.types[fixed], values.get(fixed) or {}) if fixed else "")
    value = _list_value(ctx, view.types[variable], values.get(variable) or {}) if variable else ""
    return label, value


def list_table(ctx: BuildContext, list_definition_id: int | None, config: dict | None) -> TableData | None:
    """Liste als Tabelle; ``config`` im Format der Blockkonfiguration (linked_list_*), optional
    mit eingefrorenem ``list_snapshot`` eines Protokollblocks."""
    config = config if isinstance(config, dict) else {}
    definition = ctx.db.get(ListDefinition, list_definition_id) if list_definition_id else None
    if definition is not None and definition.tenant_id != ctx.tenant_id:
        definition = None
    snapshot = config.get("list_snapshot")
    if isinstance(snapshot, dict) and isinstance(snapshot.get("entries"), list):
        view = _snapshot_view(snapshot, definition)
    else:
        if definition is None:
            return None
        entries = list(ctx.db.scalars(select(ListEntry).where(ListEntry.list_definition_id == definition.id).order_by(ListEntry.sort_index.asc(), ListEntry.id.asc())))
        view = _live_view(definition, entries)

    # Sichtbare Spalten des Blocks (None = alle, in der Reihenfolge der Liste)
    visible = config.get("linked_list_visible_columns")
    keys = [key for key, _title, _type in view.columns]
    if isinstance(visible, list) and visible:
        chosen = [resolved for resolved in (_resolve_key(view, definition, key) for key in visible) if resolved]
        keys = list(dict.fromkeys(chosen)) or keys
    titles = {key: title for key, title, _type in view.columns}
    columns = [TableColumn(key=key, label=titles[key]) for key in keys]
    items_source = view.entries

    filter_column = _resolve_key(view, definition, config.get("linked_list_filter_column"))
    if filter_column:
        filter_type = view.types[filter_column]
        filter_participant = ctx.ref_to_internal_id(Participant, config.get("linked_list_filter_participant_id"))
        filter_event = ctx.ref_to_internal_id(Event, config.get("linked_list_filter_event_id"))
        filter_text = str(config.get("linked_list_filter_text") or "").strip().lower()

        def matches(entry: dict) -> bool:
            value = entry["values"].get(filter_column) or {}
            if filter_type == "participant" and filter_participant:
                return ctx.ref_to_internal_id(Participant, value.get("participant_id")) == filter_participant
            if filter_type == "participants" and filter_participant:
                return filter_participant in [ctx.ref_to_internal_id(Participant, ref) for ref in (value.get("participant_ids") or [])]
            if filter_type == "event" and filter_event:
                return ctx.ref_to_internal_id(Event, value.get("event_id")) == filter_event
            if filter_text:
                return filter_text in str(_list_value(ctx, filter_type, value) or "").lower()
            return True

        items_source = [entry for entry in items_source if matches(entry)]

    group_by = _resolve_key(view, definition, config.get("linked_list_group_by")) or ""
    sort_by = _resolve_key(view, definition, config.get("linked_list_sort_by")) or ""
    descending = str(config.get("linked_list_sort_direction") or "").lower() == "desc"

    items: list[dict] = []
    for entry in items_source:
        texts = {key: _list_value(ctx, view.types[key], entry["values"].get(key) or {}) for key in keys}
        if not any(str(text).strip() for text in texts.values()):
            continue
        item = {"entry": entry, "texts": texts, "sort": "", "group": None}
        if sort_by:
            item["sort"] = sort_key(_sort_text(ctx, view.types[sort_by], entry["values"].get(sort_by) or {}))
        if group_by:
            item["group"] = inline_text(_list_value(ctx, view.types[group_by], entry["values"].get(group_by) or {}))
        items.append(item)

    items.sort(key=lambda item: (item["entry"].get("sort_index") or 0, item["entry"].get("id") or 0))
    if sort_by:
        filled = sorted((item for item in items if item["sort"]), key=lambda item: item["sort"], reverse=descending)
        items = filled + [item for item in items if not item["sort"]]

    highlight_empty = bool(config.get("linked_list_highlight_empty", False))

    def cell(value: str) -> Cell:
        if not str(value or "").strip() and highlight_empty:
            return Cell(k="text", v="—", tone="warning")
        return text_cell(value)

    if not group_by:
        rows = [TableRow(cells=[cell(item["texts"][key]) for key in keys]) for item in items]
        return TableData(columns=columns, groups=[TableGroup(rows=rows)] if rows else [])

    # Gruppiert: eine Zeile pro Gruppenwert, die Werte der anderen Spalten zusammengefasst.
    grouped: dict[str, dict] = {}
    for item in items:
        group_key = sort_key(item["group"]) or "__empty__"
        bucket = grouped.setdefault(group_key, {"label": item["group"], "texts": {key: [] for key in keys}})
        for key in keys:
            bucket["texts"][key].append(inline_text(item["texts"][key]))
    rows: list[TableRow] = []
    for bucket in grouped.values():
        label_cell = text_cell(bucket["label"]) if bucket["label"] else Cell(k="text", v="", note_key="group.noValue")
        rows.append(TableRow(cells=[
            label_cell if key == group_by else text_cell(", ".join(value for value in bucket["texts"][key] if value))
            for key in keys
        ]))
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
        "linked_list_visible_columns": params.visible_columns,
    }
    table = list_table(ctx, definition.id if definition else None, config) if definition else None
    title = spec.title if spec.title is not None else (definition.name if definition else None)
    return [ListTableBlock(**spec_fields(spec, title=title), table=table or TableData(columns=[TableColumn(key="value")]))]
