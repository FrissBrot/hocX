"""Todos (Pendenzen): Filter nach Status, Person, Tag, Fälligkeit, Protokoll; Gruppierung nach
Person, Status oder Tag. Sichtbarkeit wie in ``GET /api/todos``: eingeschränkte Leser sehen nur
Todos aus Protokollen mit Zugriff plus ihnen direkt zugewiesene."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Iterable

from app.documents.catalog import BlockSpec, TodoTableParams
from app.documents.context import BuildContext, format_amount, format_date
from app.documents.model import Cell, TableColumn, TableData, TableGroup, TableRow, TodoTableBlock
from app.documents.providers.common import amount_cell, col, sort_key, spec_fields, status_cell, tags_cell, text_cell

TODO_STATUS_ORDER = {"open": 0, "in_progress": 1, "done": 2, "cancelled": 3}
_DUE_MARKER_KEYS = {"nächste Sitzung": "due.nextSession", "letzte Sitzung": "due.lastSession"}
_LIMIT = 10_000


def status_code(row: Any) -> str:
    return getattr(row, "todo_status_code", None) or "open"


def is_open(row: Any) -> bool:
    return status_code(row) in ("open", "in_progress")


def is_overdue(row: Any, today: date) -> bool:
    """Offen und die Fälligkeit liegt vor heute (heute fällig ist noch nicht überfällig)."""
    due = getattr(row, "resolved_due_date", None)
    return is_open(row) and due is not None and due < today


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


class TodoFines:
    """Bussen je Pendenz für Dokumente und Exporte, sichtbar wie im Pendenzen-Popup
    (``GET /protocol-todos/{id}/fine``): eingefrorene Bussen (ohne gelöschte/erlassene) plus die
    laufende Busse der Personen ohne gespeicherte Busse. Beträge anderer Personen nur mit
    ``reports.personal`` oder ``finances.manage``, sonst nur die eigene Busse."""

    def __init__(self, totals: dict[int, Decimal], currency: str) -> None:
        self.totals = totals
        self.currency = currency

    def text(self, row: Any) -> str:
        total = self.totals.get(row.ProtocolTodo.id)
        return f"{format_amount(total)} {self.currency}".strip() if total else ""


def load_todo_fines(ctx: BuildContext, rows: list[Any]) -> TodoFines | None:
    """``None``, wenn der Mandant das Modul nicht hat oder keine Pendenz eine Busse trägt; dann
    erscheint auch keine Spalte."""
    from sqlalchemy import select

    from app.core.features_generated import F
    from app.core.permissions import P
    from app.models import ProtocolTodo, Tenant, TodoFine
    from app.models.entities import TenantFeature
    from app.services import todo_fine_service as fines

    todo_ids = [row.ProtocolTodo.id for row in rows if getattr(getattr(row, "ProtocolTodo", None), "id", None) is not None]
    if not todo_ids:
        return None
    booked = ctx.db.scalar(
        select(TenantFeature.id).where(
            TenantFeature.tenant_id == ctx.tenant_id, TenantFeature.feature_code == F.TODO_FINES, TenantFeature.access.in_(("full", "read_only"))
        ).limit(1)
    )
    if booked is None:
        return None
    user = ctx.user
    only_participant = None if user is None or user.can(P.FINANCES_MANAGE) else ctx.own_fines_participant_id()

    def visible(participant_id: int | None) -> bool:
        return only_participant is None or participant_id == only_participant

    totals: dict[int, Decimal] = {}
    stored: dict[int, set[int]] = {}
    for todo_id, participant_id, amount, status in ctx.db.execute(
        select(TodoFine.protocol_todo_id, TodoFine.participant_id, TodoFine.amount, TodoFine.status).where(
            TodoFine.tenant_id == ctx.tenant_id, TodoFine.protocol_todo_id.in_(todo_ids)
        )
    ):
        # Gespeichert (jeder Status) heisst: keine laufende Busse mehr für diese Person
        stored.setdefault(todo_id, set()).add(participant_id)
        if status != "deleted" and visible(participant_id):
            totals[todo_id] = totals.get(todo_id, Decimal("0")) + Decimal(amount)

    fine_ctx = fines.TenantFineContext(ctx.db, ctx.tenant_id)
    facts_rows = ctx.db.execute(fines._facts_query(ctx.tenant_id).where(ProtocolTodo.id.in_(todo_ids))).all()
    all_facts = [fines._facts_from_row(row) for row in facts_rows]
    fine_ctx.people([pid for facts in all_facts for pid in facts.assignee_ids])
    for facts in all_facts:
        # Erledigte Pendenzen: nur eingefrorene Bussen (wie im Popup nach dem Einfrieren)
        if facts.status_code not in fines.OPEN_STATUS_CODES and facts.id in stored:
            continue
        evaluation = fines.evaluate(fine_ctx, facts, on=ctx.today)
        if evaluation.state != "ok":
            continue
        for line in evaluation.lines:
            if line.participant_id in stored.get(facts.id, set()) or not visible(line.participant_id):
                continue
            totals[facts.id] = totals.get(facts.id, Decimal("0")) + line.amount
    totals = {todo_id: fines.money(total) for todo_id, total in totals.items() if total > 0}
    if not totals:
        return None
    currency = ctx.db.scalar(select(Tenant.finance_currency).where(Tenant.id == ctx.tenant_id)) or "CHF"
    return TodoFines(totals, currency)


def todo_columns(columns: Iterable[str], *, with_fine: bool = False) -> list[TableColumn]:
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
    if with_fine:
        result.append(col("fine", "col.fine", align="right"))
    return result


def todo_row(row: Any, columns: list[TableColumn], tag_config: dict | None = None, fines: TodoFines | None = None) -> TableRow:
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
        elif column.key == "fine":
            cells.append(amount_cell(fines.text(row) if fines else ""))
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


def todo_table(
    rows: list[Any], columns: list[TableColumn], *, group_by: str = "none", tag_config: dict | None = None, fines: TodoFines | None = None
) -> TableData:
    rows = sort_rows(rows)
    if group_by == "none" or not rows:
        return TableData(columns=columns, groups=[TableGroup(rows=[todo_row(row, columns, tag_config, fines) for row in rows])] if rows else [])

    groups: dict[str, TableGroup] = {}
    order: list[tuple[Any, str]] = []

    def add(key: str, group: TableGroup, rank: Any, row: Any) -> None:
        if key not in groups:
            groups[key] = group
            order.append((rank, key))
        groups[key].rows.append(todo_row(row, columns, tag_config, fines))

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
    elif params.status == "in_progress":
        rows = [row for row in rows if status_code(row) == "in_progress"]
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
    if params.overdue_only:
        rows = [row for row in rows if is_overdue(row, ctx.today)]
    if params.due_until is not None:
        rows = [
            row for row in rows
            if (row.resolved_due_date <= params.due_until if getattr(row, "resolved_due_date", None) is not None else params.include_undated)
        ]
    if params.exclude_ids:
        excluded = set(params.exclude_ids)
        rows = [row for row in rows if row.ProtocolTodo.public_id not in excluded]
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
    # Busse erscheint automatisch, sobald eine der Pendenzen eine trägt (abwählbar im Export-Dialog)
    fines = load_todo_fines(ctx, rows) if params.show_fines else None
    columns = todo_columns(params.columns, with_fine=fines is not None)
    tag_config = _tag_config(ctx) if "tags" in params.columns else None
    return [TodoTableBlock(**spec_fields(spec), table=todo_table(rows, columns, group_by=params.group_by, tag_config=tag_config, fines=fines))]


def markdown(
    rows: list[Any],
    *,
    strings: dict[str, str],
    title: str,
    group_by_person: bool,
    show_status: bool,
    today: date,
    exclude_columns: set[str] | None = None,
    fines: TodoFines | None = None,
) -> str:
    """Todo-Liste für WhatsApp: nur Formatierung, die WhatsApp kennt (*fett*, _kursiv_,
    ~durchgestrichen~), keine Tabellen oder Überschriften. Aufgabe fett, darunter je Feld eine
    eingerückte Zeile mit kursivem Label. ``exclude_columns`` = im Dialog abgewählte Spaltenköpfe."""
    excluded = exclude_columns or set()

    def plain(value: Any) -> str:
        text = " ".join(str(value or "").split())
        return text.replace("*", "∗").replace("_", "‗").replace("~", "∼").replace("`", "´")

    def wanted(key: str) -> bool:
        return strings.get(key, key) not in excluded

    def field(key: str, value: str) -> str:
        return f"    _{plain(strings[key])}:_ {value}"

    def entry(row: Any, index: int, include_assignee: bool) -> list[str]:
        code = status_code(row)
        task = plain(task_text(row)) or "–"
        task = f"~{task}~" if code in ("done", "cancelled") else f"*{task}*"
        line = f"{index}. {task}"
        if show_status and wanted("col.status"):
            line += f" _({plain(strings.get(f'todoStatus.{code}', code))})_"
        lines = [line]
        if include_assignee and wanted("col.assignee") and getattr(row, "assigned_participant_name", None):
            lines.append(field("col.assignee", plain(row.assigned_participant_name)))
        if wanted("col.due"):
            due = due_cell(row)
            due_text = due.v
            if due.note_key:
                note = strings.get(due.note_key, "")
                due_text = f"{due_text} ({note})" if due_text else note
            if due_text:
                lines.append(field("col.due", plain(due_text)))
        if wanted("col.protocol") and protocol_label(row):
            lines.append(field("col.protocol", plain(protocol_label(row))))
        if wanted("col.tags") and todo_tags(row):
            lines.append(field("col.tags", ", ".join(plain(tag) for tag in todo_tags(row))))
        if fines is not None and wanted("col.fine") and fines.text(row):
            lines.append(field("col.fine", plain(fines.text(row))))
        return lines

    as_of = strings["label.asOf"].replace("{date}", format_date(today))
    lines = [f"*{plain(title)}*", f"_{plain(as_of)} · {plain(strings['col.count'])}: {len(rows)}_", ""]
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
            lines.append(f"*{plain(label)}* ({len(groups[name])})")
            for index, row in enumerate(groups[name], start=1):
                lines.extend(entry(row, index, False))
            lines.append("")
    else:
        for index, row in enumerate(ordered, start=1):
            lines.extend(entry(row, index, True))
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)
