"""Protokoll: Meta, Elemente mit ihren Blöcken (alle Element-Typen), Sitzungsdatum,
Sitzungsnotizen, Matrix, Bilder.

Die Blöcke eines Protokolls kommen aus dem Protokoll selbst; jede Referenz in
``configuration_snapshot_json`` (Teilnehmende, Termine, Listen, Konten …) ist
benutzerkontrolliert und wird mandantengebunden aufgelöst (Audit-Findings 2026-08-25)."""
from __future__ import annotations

import logging
import re
from typing import Any

from app.core.config import settings
from app.core.element_types import element_type_code
from app.documents import repository
from app.documents.catalog import (
    BlockSpec,
    ChartParams,
    ImageGalleryParams,
    ImageParams,
    ProtocolBlockRefParams,
    ProtocolElementParams,
    ProtocolRefParams,
    SessionDateParams,
)
from app.documents.context import BuildContext, DocumentNotFoundError, format_date, format_date_range
from app.documents.model import (
    AttendanceBlock,
    BulletList,
    BulletListBlock,
    Cell,
    EntryExitBlock,
    EventTableBlock,
    FinanceBalanceBlock,
    FinanceTransactionsBlock,
    FinesBlock,
    FormBlock,
    FormRow,
    ImageBlock,
    ImageGalleryBlock,
    InlineTable,
    LineBreak,
    ListTableBlock,
    MatrixBlock,
    Paragraph,
    ProtocolElementBlock as ElementModel,
    RichTextBlock,
    SessionDateBlock,
    SessionNotesBlock,
    StaticTextBlock,
    TableColumn,
    TableData,
    TableGroup,
    TableRow,
    TextSpan,
    TodoTableBlock,
)
from app.documents.providers import events as event_provider
from app.documents.providers import finance as finance_provider
from app.documents.providers import lists as list_provider
from app.documents.providers import people as people_provider
from app.documents.providers import statistics as statistics_provider
from app.documents.providers import todos as todo_provider
from app.documents.providers.common import PROTOCOL_STATUS_CODES, spec_fields, text_cell
from app.documents.richtext import markdown_to_rich, plain_to_rich
from app.models import FinanceAccount, FinanceTransaction, ListDefinition, Protocol, ProtocolElementBlock, StoredFile
from app.services.event_filter import filter_events, normalize_event_filter
from app.core.storage import MAIN, InvalidObjectKey, ObjectNotFound, get_object_store

logger = logging.getLogger(__name__)

SESSION_NOTES_SECTION = "sitzungsnotizen"


def protocol_status_code(protocol: Protocol) -> str | None:
    return PROTOCOL_STATUS_CODES.get(protocol.status)


def trim_section_name(name: str) -> str:
    return re.sub(r"\s*\(.*\)$", "", name or "").strip()


def resolve_protocol(ctx: BuildContext, ref: Any) -> Protocol:
    protocol = ctx.require_entity(Protocol, ref) if ref else ctx.protocol
    if protocol is None:
        raise DocumentNotFoundError("Protocol")
    ctx.ensure_can_read_protocol(protocol.id)
    return protocol


# ── Blöcke eines Protokollelements ──────────────────────────────────────────


def _rich_lines(text: str) -> list[Any]:
    lines = [line for line in str(text or "").splitlines() if line.strip()]
    if not lines:
        return []
    spans: list[Any] = []
    for index, line in enumerate(lines):
        if index:
            spans.append(LineBreak())
        spans.append(TextSpan(v=line.strip()))
    return [Paragraph(c=spans)]


def _todo_block(rows: list[Any], fields: dict) -> TodoTableBlock:
    columns = ["status"]
    if any(getattr(row, "assigned_participant_name", None) for row in rows):
        columns.append("assignee")
    if any(getattr(row, "resolved_due_date", None) or getattr(row, "resolved_due_label", None) for row in rows):
        columns.append("due")
    table_columns = todo_provider.todo_columns(columns)
    table = TableData(columns=table_columns, groups=[TableGroup(rows=[todo_provider.todo_row(row, table_columns) for row in rows])] if rows else [])
    return TodoTableBlock(**fields, table=table)


def _image_ref(ctx: BuildContext, stored_file: StoredFile, caption: str | None):
    # Wie der Datei-Endpunkt: nur vom Virenscan freigegebene Dateien (nicht pending/infected/
    # error) werden dekodiert und eingebettet, sonst gilt das Bild als fehlend.
    if stored_file.scan_status == "clean":
        try:
            # Liest aus dem Objektspeicher (Namespace «main»); erst beim ersten Bedarf.
            return ctx.assets.add_image(
                lambda: get_object_store().get_bytes(MAIN, stored_file.storage_path),
                key=f"file:{stored_file.id}",
                caption=caption,
            )
        except (ObjectNotFound, InvalidObjectKey):
            pass
    from app.documents.model import ImageRef

    return ImageRef(path="assets/missing.png", caption=caption or stored_file.original_name, missing=True)


def _form_block(ctx: BuildContext, config: dict, fields: dict):
    linked_list_id = ctx.ref_to_internal_id(ListDefinition, config.get("linked_list_id"))
    if linked_list_id:
        table = list_provider.list_table(ctx, linked_list_id, config)
        return ListTableBlock(**fields, table=table or TableData(columns=[TableColumn(key="column_one")]))
    rows: list[FormRow] = []
    for row in config.get("rows") or []:
        if not isinstance(row, dict):
            continue
        row_type = row.get("value_type") or row.get("row_type") or "text"
        if row_type == "list_entry":
            label, value = list_provider.form_row_list_entry(ctx, row)
        else:
            label, value = str(row.get("label") or "").strip(), list_provider.form_row_value(ctx, row)
        if str(value).strip():
            rows.append(FormRow(label=label, value=plain_to_rich(value)))
    return FormBlock(
        **fields,
        label_heading=str(config.get("left_column_heading") or "").strip() or None,
        value_heading=str(config.get("value_column_heading") or "").strip() or None,
        rows=rows,
    )


def _event_list_block(ctx: BuildContext, protocol: Protocol, config: dict, fields: dict, column: dict | None = None) -> EventTableBlock:
    normalized = normalize_event_filter(config.get("event_filter"), default_range_mode="future")
    events = filter_events(ctx.db, event_provider.tenant_events(ctx), normalized, protocol=protocol, column=column)
    columns = [
        key for key, default in (
            ("date", True), ("tag", True), ("title", True), ("description", True), ("participant_count", False),
            ("location", False), ("organizers", False), ("cancelled", False),
        )
        if (config.get(f"event_show_{key}", default) is not False if default else config.get(f"event_show_{key}", False) is True)
    ]
    table = event_provider.event_table(
        ctx,
        events,
        columns,
        gray_past=bool(config.get("event_gray_past", True)),
        show_tag_colors=bool(config.get("event_show_tag_colors", False)),
        reference_date=protocol.protocol_date,
    )
    return EventTableBlock(**fields, table=table)


def _finance_balance_block(ctx: BuildContext, protocol: Protocol, config: dict, fields: dict) -> FinanceBalanceBlock:
    account = ctx.entity_by_ref(FinanceAccount, config.get("finance_account_id"))
    if account is None:
        return FinanceBalanceBlock(**fields, balances=[])
    as_of = protocol.protocol_date if config.get("finance_balance_date") == "protocol_date" else None
    return FinanceBalanceBlock(**fields, balances=[finance_provider.balance_line(ctx, account, as_of)])


def _finance_transactions_block(ctx: BuildContext, protocol: Protocol, config: dict, fields: dict) -> FinanceTransactionsBlock:
    from sqlalchemy import select

    from app.services.protocol_period_service import protocol_period, transaction_matches

    account = ctx.entity_by_ref(FinanceAccount, config.get("finance_account_id"))
    if account is None:
        return FinanceTransactionsBlock(**fields, table=TableData(columns=[TableColumn(key="date")]))
    transactions = list(ctx.db.scalars(select(FinanceTransaction).where(FinanceTransaction.account_id == account.id).order_by(FinanceTransaction.transaction_date.asc(), FinanceTransaction.id.asc())))
    period = protocol_period(ctx.db, protocol)
    filtered = [tx for tx in transactions if transaction_matches(tx.transaction_date, config, protocol_date=protocol.protocol_date, period=period)]
    if str(config.get("finance_filter_type") or "all") == "last_n":
        last_n = int(config.get("finance_last_n") or 10)
        filtered = filtered[-last_n:]
    opening = 0.0
    if filtered:
        index = transactions.index(filtered[0])
        opening = sum(float(tx.amount) for tx in transactions[:index])
    return FinanceTransactionsBlock(**fields, table=finance_provider.transactions_table(account, filtered, opening_balance=opening))


def _chart_block(ctx: BuildContext, config: dict, spec: BlockSpec):
    raw = {key: config.get(key) for key in ("chart_type", "cycle_config_id", "cycle_offset", "cycle_key") if config.get(key) not in (None, "")}
    try:
        params = ChartParams.model_validate(raw)
    except ValueError:
        params = ChartParams()
    return statistics_provider.provide_chart(ctx, spec, params)[0]


def _session_date_block(config: dict, fields: dict) -> SessionDateBlock:
    return SessionDateBlock(**fields, label=str(config.get("session_label") or "").strip() or None, date=format_date(config.get("selected_date")) or None)


def map_block(ctx: BuildContext, protocol: Protocol, block: ProtocolElementBlock) -> Any | None:
    """Ein Protokollblock → Katalog-Block. Unbekannte Typen ergeben den Beschreibungstext."""
    code = element_type_code(block.element_type_id)
    config = block.configuration_snapshot_json or {}
    title = block.block_title_snapshot or block.display_title_snapshot or block.title_snapshot
    fields = {"title": title, "level": 2}
    spec = BlockSpec(type="chart", title=title, level=2)

    if code == "text":
        text = repository.get_protocol_text(ctx.db, block.id)
        return RichTextBlock(**fields, content=markdown_to_rich(text.content if text else ""))
    if code == "todo":
        return _todo_block(list(repository.list_block_todos(ctx.db, protocol, block.id)), fields)
    if code == "image":
        images = [
            _image_ref(ctx, row.StoredFile, row.ProtocolImage.caption or row.ProtocolImage.title or row.StoredFile.original_name)
            for row in repository.list_protocol_images(ctx.db, block.id)
        ]
        return ImageGalleryBlock(**fields, images=images, columns=1)
    if code == "form":
        return _form_block(ctx, config, fields)
    if code == "event_list":
        return _event_list_block(ctx, protocol, config, fields)
    if code == "bullet_list":
        return BulletListBlock(**fields, items=[str(item) for item in (config.get("bullet_items") or []) if str(item).strip()])
    if code == "attendance":
        return AttendanceBlock(**fields, entries=people_provider.attendance_entries(ctx, config))
    if code == "session_date":
        return _session_date_block(config, fields)
    if code == "matrix":
        return MatrixBlock(**fields, tables=matrix_tables(ctx, protocol, config))
    if code == "finance_balance":
        return _finance_balance_block(ctx, protocol, config, fields)
    if code == "finance_transactions":
        return _finance_transactions_block(ctx, protocol, config, fields)
    if code == "fine_list":
        return FinesBlock(**fields, table=finance_provider.protocol_fines(ctx, protocol, config))
    if code == "chart":
        return _chart_block(ctx, config, spec)
    if code == "entry_exit":
        joins, leaves = people_provider.entry_exit_from_config(config)
        return EntryExitBlock(**fields, joins=joins, leaves=leaves)
    if code == "session_notes":
        return SessionNotesBlock(**fields, content=markdown_to_rich(protocol.session_notes or "", hard_breaks=True))
    return StaticTextBlock(**fields, content=markdown_to_rich(block.description_snapshot or ""))


def element_blocks(ctx: BuildContext, protocol: Protocol, *, element_ref: Any = None, include_session_todos: bool = True) -> list[ElementModel]:
    """Alle exportsichtbaren Elemente (oder eines) eines Protokolls als ``protocol_element``."""
    from app.services.responsible_label_service import resolve_display_section_titles_batch

    elements = repository.list_protocol_elements(ctx.db, protocol.id)
    if element_ref is not None:
        from app.models import ProtocolElement

        element_id = ctx.ref_to_internal_id(ProtocolElement, element_ref)
        elements = [element for element in elements if element.id == element_id]
        if not elements:
            raise DocumentNotFoundError("ProtocolElement")
    titles = resolve_display_section_titles_batch(ctx.db, elements, protocol.status, protocol.tenant_id)
    agenda_by_element, agenda_other = _agenda_blocks(ctx, protocol)
    result: list[ElementModel] = []
    for element in elements:
        if not element.export_visible_snapshot:
            continue
        section_title = titles.get(element.id) or element.section_name_snapshot
        if trim_section_name(section_title).lower() == SESSION_NOTES_SECTION:
            continue
        children = []
        for block in repository.list_element_blocks(ctx.db, element.id):
            if not block.export_visible_snapshot:
                continue
            mapped = map_block(ctx, protocol, block)
            if mapped is not None:
                children.append(mapped)
        # Anliegen (agenda_item) erscheinen ohne eigenen Block unter ihrem Punkt.
        children.extend(agenda_by_element.get(element.id, []))
        # Dynamische Sitzungs-Todos: Todos mit dem Abschnittsnamen als Tag.
        tag = trim_section_name(section_title).lower()
        if include_session_todos and tag:
            rows = list(repository.list_todos_by_tag(ctx.db, protocol, tag))
            if rows:
                children.append(_todo_block(rows, {"title": None, "title_key": "label.sessionTodos", "level": 2}))
        result.append(ElementModel(title=section_title, level=1, children=children))
    if element_ref is None and agenda_other:
        result.append(ElementModel(title=None, title_key="label.agendaOther", level=1, children=agenda_other))
    return result


def _agenda_blocks(ctx: BuildContext, protocol: Protocol) -> tuple[dict[int, list[RichTextBlock]], list[RichTextBlock]]:
    """Anliegen des Protokolls je Element; ohne passendes Element in der zweiten Liste."""
    from app.services.agenda_item_service import AgendaItemService

    agenda = AgendaItemService()
    items = agenda.items_for_protocol(ctx.db, protocol)
    placements = agenda.placements(ctx.db, protocol, items)
    by_element: dict[int, list[RichTextBlock]] = {}
    other: list[RichTextBlock] = []
    for item in items:
        block = RichTextBlock(
            title=None,
            level=2,
            content=[Paragraph(c=[TextSpan(v=item.title, b=True)]), *markdown_to_rich(item.body or "")],
        )
        element_id = placements.get(item.id)
        if element_id is None:
            other.append(block)
        else:
            by_element.setdefault(element_id, []).append(block)
    return by_element, other


# ── Matrix ──────────────────────────────────────────────────────────────────


def _matrix_cell(column: dict, row_id: str) -> dict:
    values = column.get("row_values") or column.get("values") or {}
    cell = values.get(row_id) if isinstance(values, dict) else None
    return cell if isinstance(cell, dict) else {}


def _matrix_events(ctx: BuildContext, protocol: Protocol, row_config: dict, column: dict) -> list[Any]:
    event_filter = normalize_event_filter(row_config.get("event_filter"), default_range_mode="future")
    return filter_events(ctx.db, event_provider.tenant_events(ctx), event_filter, protocol=protocol, column=column)


def _matrix_event_lines(ctx: BuildContext, protocol: Protocol, row: dict, column: dict) -> list[Any]:
    row_config = row.get("row_config") if isinstance(row.get("row_config"), dict) else {}
    events = _matrix_events(ctx, protocol, row_config, column)
    show_date = bool(row_config.get("event_show_date", True))
    show_count = bool(row_config.get("event_show_participant_count", False))
    gray_past = bool(row_config.get("event_gray_past", True))
    spans: list[Any] = []
    for event in events:
        end = event.event_end_date or event.event_date
        line = format_date_range(event.event_date, end) if show_date else event.title
        if show_count and event.participant_count:
            line = f"{line} ({event.participant_count})"
        if not line.strip():
            continue
        if spans:
            spans.append(LineBreak())
        spans.append(TextSpan(v=line, i=bool(gray_past and end < protocol.protocol_date)))
    return [Paragraph(c=spans)] if spans else []


def _embedded_block(ctx: BuildContext, protocol: Protocol, embedded: dict, column: dict | None) -> list[Any]:
    try:
        type_id = int(embedded.get("element_type_id") or 0)
    except (TypeError, ValueError):
        return []
    config = embedded.get("configuration_snapshot_json") if isinstance(embedded.get("configuration_snapshot_json"), dict) else {}
    code = element_type_code(type_id)
    if code in ("text", "static_text"):
        return markdown_to_rich(str(embedded.get("text_content") or ""))
    if code == "todo":
        items = [item for item in (config.get("todo_items") or []) if isinstance(item, dict) and str(item.get("task") or "").strip()]
        return [BulletList(items=[[Paragraph(c=[TextSpan(v=("☑ " if item.get("done") else "☐ ") + str(item["task"]).strip())])] for item in items])] if items else []
    if code == "image":
        labels = [str(item.get("caption") or item.get("url") or "").strip() for item in (config.get("images") or []) if isinstance(item, dict)]
        return _rich_lines("\n".join(label for label in labels if label))
    if code == "form":
        block = _form_block(ctx, config, {})
        if isinstance(block, ListTableBlock):
            rows = [[cell.v for cell in row.cells] for group in block.table.groups for row in group.rows]
            header = [column.label or "" for column in block.table.columns]
            return [InlineTable(header=header, rows=rows)] if rows else []
        rows = [[row.label, " ".join(span.v for node in row.value for span in getattr(node, "c", []) if isinstance(span, TextSpan))] for row in block.rows]
        return [InlineTable(rows=rows)] if rows else []
    if code == "event_list":
        block = _event_list_block(ctx, protocol, config, {}, column)
        lines = [" · ".join(cell.v for cell in row.cells if cell.v and cell.v != "–") for group in block.table.groups for row in group.rows]
        return _rich_lines("\n".join(lines))
    if code == "bullet_list":
        items = [str(item).strip() for item in (config.get("bullet_items") or []) if str(item or "").strip()]
        return [BulletList(items=[[Paragraph(c=[TextSpan(v=item)])] for item in items])] if items else []
    if code == "attendance":
        entries = people_provider.attendance_entries(ctx, config)
        rows: list[Any] = []
        for entry in entries:
            if rows:
                rows.append(LineBreak())
            rows.append(TextSpan(v=f"{entry.name}: "))
            rows.append(TextSpan(v="–", key=f"attendanceStatus.{entry.status}" if entry.status else None))
        return [Paragraph(c=rows)] if rows else []
    if code == "session_date":
        label = str(config.get("session_label") or "").strip()
        date_text = format_date(config.get("selected_date"))
        spans: list[Any] = [TextSpan(v=label, key=None if label else "label.nextSession"), TextSpan(v=": ")]
        spans.append(TextSpan(v=date_text) if date_text else TextSpan(v="", key="label.open"))
        return [Paragraph(c=spans)]
    return []


def _single_value(ctx: BuildContext, protocol: Protocol, value_type: str, cell: dict, row: dict, column: dict) -> list[Any]:
    from app.models import Event, Participant

    if value_type == "participant":
        participant = ctx.entity_by_ref(Participant, cell.get("participant_id") or row.get("template_participant_id"))
        return _rich_lines(participant.display_name if participant else "")
    if value_type == "participants":
        refs = cell.get("participant_ids") or row.get("template_participant_ids") or []
        names = [participant.display_name for participant in (ctx.entity_by_ref(Participant, ref) for ref in refs) if participant]
        return _rich_lines(", ".join(names))
    if value_type == "event":
        event = ctx.entity_by_ref(Event, cell.get("event_id") or row.get("template_event_id"))
        return _rich_lines(event_provider.event_inline_label(event) if event else "")
    if value_type == "events":
        row_config = row.get("row_config") if isinstance(row.get("row_config"), dict) else {}
        events = _matrix_events(ctx, protocol, row_config, column)
        return _rich_lines("\n".join(event_provider.event_inline_label(event, row_config) for event in events))
    return _rich_lines(str(cell.get("text_value") or row.get("template_value") or "").strip())


def _matrix_value(ctx: BuildContext, protocol: Protocol, row: dict, column: dict) -> list[Any]:
    cell = _matrix_cell(column, str(row.get("id") or ""))
    embedded = cell.get("embedded_block")
    if isinstance(embedded, dict) and embedded.get("element_type_id"):
        return _embedded_block(ctx, protocol, embedded, column)
    row_type = str(row.get("row_type") or "text")
    if row_type not in {"text", "participant", "participants", "event", "events"}:
        try:
            embedded_type = int(row_type)
        except (TypeError, ValueError):
            return []
        if element_type_code(embedded_type) == "event_list":
            return _matrix_event_lines(ctx, protocol, row, column)
        return []
    return _single_value(ctx, protocol, row_type, cell, row, column)


def matrix_tables(ctx: BuildContext, protocol: Protocol, config: dict) -> list[TableData]:
    """Matrix in Gruppen zu drei Spalten (wie bisher), Zellen als Rich Text."""
    rows = sorted(config.get("rows") or [], key=lambda entry: (entry.get("sort_index", 0), str(entry.get("id", ""))))
    columns = [column for column in (config.get("columns") or []) if isinstance(column, dict) and not column.get("hidden")]
    if not rows or not columns:
        return []
    left_heading = str(config.get("left_column_heading") or "").strip()
    tables: list[TableData] = []
    for start in range(0, len(columns), 3):
        group = columns[start:start + 3]
        table_columns = [TableColumn(key="label", label=left_heading or "", width="auto")] + [
            TableColumn(key=f"c{index}", label=str(column.get("title") or "").strip(), width="fill") for index, column in enumerate(group)
        ]
        table_rows: list[TableRow] = []
        for row in rows:
            values = [_matrix_value(ctx, protocol, row, column) for column in group]
            if not any(values):
                continue
            label = str(row.get("label") or "").strip()
            table_rows.append(TableRow(cells=[text_cell(label), *(Cell(k="rich", rich=value) for value in values)]))
        if table_rows:
            show_header = bool(left_heading or any(str(column.get("title") or "").strip() for column in group))
            tables.append(TableData(columns=table_columns, groups=[TableGroup(rows=table_rows)], show_header=show_header))
    return tables


# ── Katalog-Provider ────────────────────────────────────────────────────────


# Inhaltsfilter der Elemente (Kurz-/Beschlussprotokoll): erlaubte Kind-Blöcke, None = alle
_TEXT_BLOCKS = frozenset({"richtext", "static_text", "bullet_list", "form", "session_date", "session_notes"})
CONTENT_FILTERS: dict[str, frozenset[str] | None] = {"all": None, "text": _TEXT_BLOCKS, "text_and_todos": _TEXT_BLOCKS | {"todo_table"}}


def provide_protocol_element(ctx: BuildContext, spec: BlockSpec, params: ProtocolElementParams):
    protocol = resolve_protocol(ctx, params.protocol_id)
    if params.protocol_id is None or (ctx.protocol is not None and protocol.id == ctx.protocol.id):
        _refresh_membership(ctx, protocol)
    blocks = element_blocks(ctx, protocol, element_ref=params.element_id, include_session_todos=params.include_session_todos)
    if params.titles_only:
        return [BulletListBlock(**spec_fields(spec), items=[block.title or "" for block in blocks if block.title])]
    allowed = CONTENT_FILTERS.get(params.content)
    for block in blocks:
        block.children = [
            child
            for child in block.children
            if (allowed is None or child.type in allowed) and (params.include_images or child.type not in ("image", "image_gallery"))
        ]
    if spec.title and len(blocks) == 1:
        blocks[0].title = spec.title
    for block in blocks:
        block.hide_if_empty = spec.hide_if_empty
        block.level = spec.level
        for child in block.children:
            child.level = min(spec.level + 1, 4)
    return blocks


def _refresh_membership(ctx: BuildContext, protocol: Protocol) -> None:
    """Mitgliedschaftsblöcke offener Protokolle nachführen (wie vor jedem früheren Export).
    Ohne Commit: der Render-Service committet, die Vorschau rollt zurück."""
    from app.services.protocol_service import ProtocolService

    ProtocolService().refresh_membership_blocks(ctx.db, protocol.id, commit=False)


def provide_session_date(ctx: BuildContext, spec: BlockSpec, params: SessionDateParams):
    if params.session_date is not None:
        return [SessionDateBlock(**spec_fields(spec), label=params.label, date=format_date(params.session_date))]
    if params.protocol_id is None and ctx.protocol is None:
        return [SessionDateBlock(**spec_fields(spec), label=params.label, date=None)]
    protocol = resolve_protocol(ctx, params.protocol_id)
    for element in repository.list_protocol_elements(ctx.db, protocol.id):
        for block in repository.list_element_blocks(ctx.db, element.id):
            if element_type_code(block.element_type_id) == "session_date":
                result = _session_date_block(block.configuration_snapshot_json or {}, spec_fields(spec))
                if params.label:
                    result.label = params.label
                return [result]
    return [SessionDateBlock(**spec_fields(spec), label=params.label, date=None)]


def provide_session_notes(ctx: BuildContext, spec: BlockSpec, params: ProtocolRefParams):
    protocol = resolve_protocol(ctx, params.protocol_id)
    return [SessionNotesBlock(**spec_fields(spec), content=markdown_to_rich(protocol.session_notes or "", hard_breaks=True))]


def _protocol_block(ctx: BuildContext, ref: Any) -> tuple[Protocol, ProtocolElementBlock]:
    from app.models import ProtocolElement

    block_id = ctx.ref_to_internal_id(ProtocolElementBlock, ref)
    block = ctx.db.get(ProtocolElementBlock, block_id) if block_id else None
    element = ctx.db.get(ProtocolElement, block.protocol_element_id) if block is not None else None
    protocol = ctx.db.get(Protocol, element.protocol_id) if element is not None else None
    if protocol is None or protocol.tenant_id != ctx.tenant_id:
        raise DocumentNotFoundError("ProtocolElementBlock")
    ctx.ensure_can_read_protocol(protocol.id)
    return protocol, block


def provide_matrix(ctx: BuildContext, spec: BlockSpec, params: ProtocolBlockRefParams):
    if params.protocol_block_id is None:
        return [MatrixBlock(**spec_fields(spec), tables=[])]
    protocol, block = _protocol_block(ctx, params.protocol_block_id)
    if element_type_code(block.element_type_id) != "matrix":
        raise DocumentNotFoundError("ProtocolElementBlock")
    title = spec.title if spec.title is not None else (block.block_title_snapshot or block.title_snapshot)
    return [MatrixBlock(**spec_fields(spec, title=title), tables=matrix_tables(ctx, protocol, block.configuration_snapshot_json or {}))]


def provide_image(ctx: BuildContext, spec: BlockSpec, params: ImageParams):
    if params.file_id is None:
        return [ImageBlock(**spec_fields(spec), image=None)]
    stored_file = ctx.require_entity(StoredFile, params.file_id)
    if ctx.user is not None:
        from app.services.access_service import AccessService

        try:
            AccessService().ensure_can_read_stored_file(ctx.db, ctx.user, stored_file.id)
        except Exception as exc:  # HTTPException aus dem Access-Service → Rechtefehler
            from app.documents.context import DocumentPermissionError

            raise DocumentPermissionError("file") from exc
    return [ImageBlock(**spec_fields(spec), image=_image_ref(ctx, stored_file, params.caption))]


def provide_image_gallery(ctx: BuildContext, spec: BlockSpec, params: ImageGalleryParams):
    images = []
    if params.file_ids:
        for ref in params.file_ids:
            image = provide_image(ctx, BlockSpec(type="image"), ImageParams(file_id=ref))[0].image
            if image is not None:
                images.append(image)
    elif params.protocol_id is not None or ctx.protocol is not None:
        protocol = resolve_protocol(ctx, params.protocol_id)
        for element in repository.list_protocol_elements(ctx.db, protocol.id):
            for block in repository.list_element_blocks(ctx.db, element.id):
                if element_type_code(block.element_type_id) == "image" and block.export_visible_snapshot:
                    for row in repository.list_protocol_images(ctx.db, block.id):
                        images.append(_image_ref(ctx, row.StoredFile, row.ProtocolImage.caption or row.ProtocolImage.title))
    return [ImageGalleryBlock(**spec_fields(spec), images=images, columns=params.columns)]
