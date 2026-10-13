"""Todos (Pendenzen): Filter nach Status, Person, Tag, Fälligkeit, Protokoll; Gruppierung nach
Person, Status oder Tag. Sichtbarkeit wie in ``GET /api/todos``: eingeschränkte Leser sehen nur
Todos aus Protokollen mit Zugriff plus ihnen direkt zugewiesene."""
from __future__ import annotations

from datetime import date
from typing import Any, Iterable

from app.documents.catalog import BlockSpec, TodoTableParams
from app.documents.context import BuildContext, format_date
from app.documents.model import Cell, TableColumn, TableData, TableGroup, TableRow, TodoTableBlock
from app.documents.providers.common import col, sort_key, spec_fields, status_cell, tags_cell, text_cell

TODO_STATUS_ORDER = {"open": 0, "in_progress": 1, "done": 2, "cancelled": 3}
_DUE_MARKER_KEYS = {"naechste Sitzung": "due.nextSession", "letzte Sitzung": "due.lastSession"}
_LIMIT = 10_000


def status_code(row: Any) -> str:
    return getattr(row, "todo_status_code", None) or "open"


def is_open(row: Any) -> bool:
    return status_code(row) in ("open", "in_progress")


def due_cell(row: Any) -> Cell:
    """Fälligkeit: Datum plus Termin-Titel (Benutzertext) oder übersetzter Marker."""
    resolved = getattr(row, "resolved_due_date", None)
    label = getattr(row, "resolved_due_label", None)
    note_key = _DUE_MARKER_KEYS.get(str(label or ""))
    value = format_date(resolved) if resolved else ""
    if label and not note_key:
        value = f"{value} ({label})" if value else str(label)
    return Cell(k="text", v=value, note_key=note_key)


def task_text(row: Any) -> str:
    return str(getattr(row.ProtocolTodo, "task", "") or "")


def todo_tags(row: Any) -> list[str]:
    return [str(tag) for tag in (getattr(row.ProtocolTodo, "tags", None) or []) if str(tag).strip()]


def protocol_label(row: Any) -> str:
    parts = [str(value) for value in (getattr(row, "protocol_number", None), getattr(row, "protocol_title", None)) if value]
    return " · ".join(parts)


def todo_columns(columns: Iterable[str]) -> list[TableColumn]:
    wanted = list(columns)
    result: list[TableColumn] = []
    if "status" in wanted:
        result.append(col("status", "col.status"))
    result.append(col("task", "col.task", width="fill"))
    if "assignee" in wanted:
        result.append(col("assignee", "col.assignee"))
    if "due" in wanted:
        result.append(col("due", "col.due"))
    if "protocol" in wanted:
        result.append(col("protocol", "col.protocol"))
    if "tags" in wanted:
        result.append(col("tags", "col.tags"))
    return result


def todo_row(row: Any, columns: list[TableColumn], tag_config: dict | None = None) -> TableRow:
    code = status_code(row)
    cells: list[Cell] = []
    for column in columns:
        if column.key == "status":
            cells.append(status_cell(f"todoStatus.{code}"))
        elif column.key == "task":
            cells.append(text_cell(task_text(row)))
        elif column.key == "assignee":
            cells.append(text_cell(getattr(row, "assigned_participant_name", None) or ""))
        elif column.key == "due":
            cells.append(due_cell(row))
        elif column.key == "protocol":
            cells.append(text_cell(protocol_label(row)))
        elif column.key == "tags":
            cells.append(tags_cell(todo_tags(row), tag_config))
    return TableRow(cells=cells, muted=code in ("done", "cancelled"))


def sort_rows(rows: list[Any]) -> list[Any]:
    """Offene zuerst, dann nach Fälligkeit (ohne Datum zuletzt), Person, Protokoll, Aufgabe."""
    return sorted(
        rows,
        key=lambda row: (
            0 if is_open(row) else (1 if status_code(row) == "done" else 2),
            1 if getattr(row, "resolved_due_date", None) is None else 0,
            getattr(row, "resolved_due_date", None) or date.max,
            sort_key(getattr(row, "assigned_participant_name", None)),
            sort_key(getattr(row, "protocol_number", None)),
            sort_key(task_text(row)),
        ),
    )


def todo_table(rows: list[Any], columns: list[TableColumn], *, group_by: str = "none", tag_config: dict | None = None) -> TableData:
    rows = sort_rows(rows)
    if group_by == "none" or not rows:
        return TableData(columns=columns, groups=[TableGroup(rows=[todo_row(row, columns, tag_config) for row in rows])] if rows else [])

    groups: dict[str, TableGroup] = {}
    order: list[tuple[Any, str]] = []

    def add(key: str, group: TableGroup, rank: Any, row: Any) -> None:
        if key not in groups:
            groups[key] = group
            order.append((rank, key))
        groups[key].rows.append(todo_row(row, columns, tag_config))

    for row in rows:
        if group_by == "person":
            name = getattr(row, "assigned_participant_name", None)
            if name:
                add(f"p:{name}", TableGroup(label=name), (0, sort_key(name)), row)
            else:
                add("p:", TableGroup(label_key="group.unassigned"), (1, ""), row)
        elif group_by == "status":
            code = status_code(row)
            add(f"s:{code}", TableGroup(label_key=f"todoStatus.{code}"), (TODO_STATUS_ORDER.get(code, 9), ""), row)
        elif group_by == "tag":
            tags = todo_tags(row)
            if not tags:
                add("t:", TableGroup(label_key="group.noTag"), (1, ""), row)
            for tag in tags:
                add(f"t:{tag}", TableGroup(label=tag), (0, sort_key(tag)), row)
    return TableData(columns=columns, groups=[groups[key] for _, key in sorted(order)])


def list_tenant_todo_rows(ctx: BuildContext) -> list[Any]:
    from app.repositories.protocol_todo_repository import ProtocolTodoRepository
    from app.services.access_service import AccessService

    repository = ProtocolTodoRepository()
    user = ctx.user
    if user is not None:
        access = AccessService()
        if access._is_restricted_reader(ctx.db, user):
            protocol_ids = access.repository.list_protocol_ids(ctx.db, user_id=user.user_id, tenant_id=ctx.tenant_id)
            return list(repository.list_for_protocols_or_assigned(ctx.db, ctx.tenant_id, protocol_ids, user.user_id, skip=0, limit=_LIMIT))
    return list(repository.list_for_tenant(ctx.db, ctx.tenant_id, skip=0, limit=_LIMIT))


def filter_rows(ctx: BuildContext, rows: list[Any], params: TodoTableParams) -> list[Any]:
    from app.models import Participant, Protocol

    if params.status == "open":
        rows = [row for row in rows if is_open(row)]
    elif params.status == "done":
        rows = [row for row in rows if status_code(row) == "done"]
    if params.participant_id is not None:
        participant_id = ctx.ref_to_internal_id(Participant, params.participant_id)
        rows = [
            row for row in rows
            if participant_id is not None and (
                getattr(row.ProtocolTodo, "assigned_participant_id", None) == participant_id
                or participant_id in (getattr(row, "assignee_ids", None) or [])
            )
        ]
    if params.tag:
        wanted = params.tag.strip().casefold()
        rows = [row for row in rows if any(tag.casefold() == wanted for tag in todo_tags(row))]
    if params.due_until is not None:
        rows = [row for row in rows if getattr(row, "resolved_due_date", None) is None or row.resolved_due_date <= params.due_until]
    if params.protocol_id is not None:
        protocol = ctx.entity_by_ref(Protocol, params.protocol_id)
        protocol_internal_id = protocol.id if protocol is not None else -1
        rows = [row for row in rows if getattr(row, "protocol_id", None) == protocol_internal_id]
    return rows


def _tag_config(ctx: BuildContext) -> dict:
    from app.models import Tenant

    tenant = ctx.db.get(Tenant, ctx.tenant_id)
    return (tenant.tag_config_json or {}) if tenant is not None else {}


def provide(ctx: BuildContext, spec: BlockSpec, params: TodoTableParams):
    rows = filter_rows(ctx, list_tenant_todo_rows(ctx), params)
    columns = todo_columns(params.columns)
    tag_config = _tag_config(ctx) if "tags" in params.columns else None
    return [TodoTableBlock(**spec_fields(spec), table=todo_table(rows, columns, group_by=params.group_by, tag_config=tag_config))]


def markdown(rows: list[Any], *, strings: dict[str, str], title: str, group_by_person: bool, show_status: bool, today: date) -> str:
    """Todo-Liste als WhatsApp-taugliches Markdown (wie der frühere Markdown-Export)."""

    def plain(value: Any) -> str:
        text = " ".join(str(value or "").split())
        return text.replace("*", "∗").replace("_", "‗").replace("~", "∼").replace("`", "´")

    def entry(row: Any, index: int, include_assignee: bool) -> list[str]:
        code = status_code(row)
        task = plain(task_text(row)) or "–"
        if code in ("done", "cancelled"):
            task = f"~{task}~"
        line = f"{index}. {task}"
        if show_status:
            line += f" [{strings.get(f'todoStatus.{code}', code)}]"
        lines = [line]
        if include_assignee and getattr(row, "assigned_participant_name", None):
            lines.append(f"   {strings['col.assignee']}: {plain(row.assigned_participant_name)}")
        due = due_cell(row)
        due_text = due.v
        if due.note_key:
            note = strings.get(due.note_key, "")
            due_text = f"{due_text} ({note})" if due_text else note
        if due_text:
            lines.append(f"   {strings['col.due']}: {plain(due_text)}")
        if protocol_label(row):
            lines.append(f"   {strings['col.protocol']}: {plain(protocol_label(row))}")
        if todo_tags(row):
            lines.append(f"   {strings['col.tags']}: {', '.join(plain(tag) for tag in todo_tags(row))}")
        lines.append("")
        return lines

    lines = [f"*{plain(title)}*", strings["label.asOf"].replace("{date}", format_date(today)), f"{strings['col.count']}: {len(rows)}", ""]
    if not rows:
        lines.append(strings["empty.todo_table"])
        return "\n".join(lines)
    ordered = sort_rows(rows)
    if group_by_person:
        groups: dict[str, list[Any]] = {}
        for row in ordered:
            groups.setdefault(getattr(row, "assigned_participant_name", None) or "", []).append(row)
        for name in sorted(groups, key=lambda value: (value == "", sort_key(value))):
            label = name or strings["group.unassigned"]
            lines.append(f"*{plain(label)} ({len(groups[name])})*")
            for index, row in enumerate(groups[name], start=1):
                lines.extend(entry(row, index, False))
    else:
        for index, row in enumerate(ordered, start=1):
            lines.extend(entry(row, index, True))
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)
