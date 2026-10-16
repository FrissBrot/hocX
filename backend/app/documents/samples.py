"""Beispielinhalte der Fachkomponenten für die Vorschau im Designer (``data_mode="sample"``).

Nur der Vorschau-Endpunkt darf Beispieldaten verwenden; der Export (``/render``) lehnt sie ab.
Alle Texte stammen aus documentPdf (``sample.*`` und die normalen Status-/Spaltenschlüssel),
damit die Vorschau in jeder Dokumentsprache stimmt. Die Blöcke durchlaufen dieselbe Typst-
Darstellung wie echte Daten.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Callable

from app.documents.catalog import BlockSpec
from app.documents.context import format_amount, format_date
from app.documents.model import (
    AgendaItem,
    AgendaMonth,
    AttendanceBlock,
    AttendanceEntry,
    AttendanceMatrixBlock,
    AttendanceSheetBlock,
    BalanceLine,
    BulletList,
    BulletListBlock,
    CalendarEvent,
    CalendarMonth,
    Cell,
    ChartBlock,
    ChartSeries,
    EntryExitBlock,
    EntryExitItem,
    EventAgendaBlock,
    EventCalendarMonthBlock,
    EventTableBlock,
    FinanceBalanceBlock,
    FinanceTransactionsBlock,
    FinesBlock,
    FormBlock,
    FormRow,
    ImageBlock,
    ImageGalleryBlock,
    KpiTile,
    KpiTilesBlock,
    ListTableBlock,
    MatrixBlock,
    MemberListBlock,
    Paragraph,
    ProtocolElementBlock,
    RichTextBlock,
    SessionDateBlock,
    SessionNotesBlock,
    SignatureField,
    SignatureFieldsBlock,
    StatTableBlock,
    TableColumn,
    TableData,
    TableGroup,
    TableRow,
    TextSpan,
    TodoTableBlock,
)

SampleFn = Callable[[BlockSpec, Any, dict[str, str]], list[Any]]


def _t(strings: dict[str, str], key: str) -> str:
    return strings.get(f"sample.{key}", "")


def _fields(spec: BlockSpec) -> dict[str, Any]:
    return {"title": spec.title, "hide_if_empty": spec.hide_if_empty, "level": spec.level}


def _paragraph(text: str) -> list[Any]:
    return [Paragraph(c=[TextSpan(v=text)])]


def _text(value: str, **kwargs: Any) -> Cell:
    return Cell(k="text", v=value, **kwargs)


def _todo_table(strings: dict[str, str], count: int = 3) -> TableData:
    columns = [
        TableColumn(key="task", label_key="col.task", width="fill"),
        TableColumn(key="status", label_key="col.status"),
        TableColumn(key="assignee", label_key="col.assignee"),
        TableColumn(key="due", label_key="col.due"),
    ]
    statuses = ["todoStatus.open", "todoStatus.in_progress", "todoStatus.done"]
    rows = [
        TableRow(
            cells=[
                _text(_t(strings, f"task{index}")),
                Cell(k="status", status=statuses[(index - 1) % 3]),
                _text(_t(strings, f"person{index}")),
                _text(format_date(date(2026, 4, index * 3))),
            ]
        )
        for index in range(1, count + 1)
    ]
    return TableData(columns=columns, groups=[TableGroup(rows=rows)])


def _protocol_element(spec: BlockSpec, params: Any, strings: dict[str, str]) -> list[Any]:
    if getattr(params, "titles_only", False):
        return [BulletListBlock(**_fields(spec), items=[_t(strings, f"section{index}") for index in range(1, 5)])]
    content = getattr(params, "content", "all")
    blocks = []
    for index in range(1, 4):
        children: list[Any] = [RichTextBlock(level=min(spec.level + 1, 4), content=_paragraph(_t(strings, f"paragraph{index}")))]
        if index == 2:
            children.append(BulletListBlock(level=min(spec.level + 1, 4), items=[_t(strings, f"bullet{item}") for item in range(1, 4)]))
        if content != "text" and index == 3:
            children.append(TodoTableBlock(title_key="label.sessionTodos", level=min(spec.level + 1, 4), table=_todo_table(strings, 2)))
        blocks.append(ProtocolElementBlock(title=_t(strings, f"section{index}"), level=spec.level, hide_if_empty=spec.hide_if_empty, children=children))
    return blocks


def _session_date(spec, params, strings):
    return [SessionDateBlock(**_fields(spec), label=getattr(params, "label", None), date=format_date(date(2026, 4, 9)))]


def _session_notes(spec, params, strings):
    return [SessionNotesBlock(**_fields(spec), content=_paragraph(_t(strings, "paragraph1")))]


def _form(spec, params, strings):
    rows = [FormRow(label=row.label, value=_paragraph(row.value)) for row in getattr(params, "rows", [])] or [
        FormRow(label=_t(strings, f"formLabel{index}"), value=_paragraph(_t(strings, f"formValue{index}"))) for index in range(1, 4)
    ]
    return [FormBlock(**_fields(spec), label_heading=getattr(params, "label_heading", None), value_heading=getattr(params, "value_heading", None), rows=rows)]


def _matrix(spec, params, strings):
    columns = [TableColumn(key="row", label=""), *(TableColumn(key=f"c{index}", label=_t(strings, f"person{index}")) for index in range(1, 4))]
    rows = [TableRow(cells=[_text(_t(strings, f"event{row}")), *(Cell(k="rich", rich=_paragraph(_t(strings, "yes") if (row + col) % 2 else "–")) for col in range(1, 4))]) for row in range(1, 4)]
    return [MatrixBlock(**_fields(spec), tables=[TableData(columns=columns, groups=[TableGroup(rows=rows)])])]


def _entry_exit(spec, params, strings):
    return [EntryExitBlock(**_fields(spec), joins=[EntryExitItem(name=_t(strings, "person4"), date=format_date(date(2026, 2, 1)))], leaves=[EntryExitItem(name=_t(strings, "person5"), date=format_date(date(2026, 1, 31)))])]


def _image(spec, params, strings):
    from app.documents.model import ImageRef

    return [ImageBlock(**_fields(spec), image=ImageRef(path="assets/missing.png", caption=getattr(params, "caption", None) or _t(strings, "imageCaption"), missing=True))]


def _gallery(spec, params, strings):
    from app.documents.model import ImageRef

    images = [ImageRef(path="assets/missing.png", caption=_t(strings, "imageCaption"), missing=True) for _ in range(2)]
    return [ImageGalleryBlock(**_fields(spec), images=images, columns=getattr(params, "columns", 2))]


def _attendance(spec, params, strings):
    statuses = ["present", "present", "late", "excused", "absent", "present"]
    entries = [AttendanceEntry(name=_t(strings, f"person{index}"), status=statuses[index - 1]) for index in range(1, 7)]
    return [AttendanceBlock(**_fields(spec), entries=entries)]


def _attendance_matrix(spec, params, strings):
    people = [_t(strings, f"person{index}") for index in range(1, 5)]
    sessions = [format_date(date(2026, month, 10))[:5] for month in range(1, 6)]
    cycle = ["present", "excused", "present", "absent", "late"]
    cells = [[cycle[(row + col) % 5] for col in range(5)] for row in range(4)]
    return [AttendanceMatrixBlock(**_fields(spec), sessions=sessions, people=people, cells=cells, rates=["80%", "60%", "80%", "60%"] if getattr(params, "show_rates", True) else [])]


def _member_list(spec, params, strings):
    columns = [TableColumn(key="name", label_key="col.name", width="fill"), TableColumn(key="email", label_key="col.email"), TableColumn(key="joined_at", label_key="col.joined")]
    rows = [TableRow(cells=[_text(_t(strings, f"person{index}")), _text(f"person{index}@example.ch"), _text(format_date(date(2019 + index, 1, 15)))]) for index in range(1, 6)]
    return [MemberListBlock(**_fields(spec), table=TableData(columns=columns, groups=[TableGroup(rows=rows)]))]


def _signature_fields(spec, params, strings):
    fields = [SignatureField(label=field.label, name=field.name) for field in getattr(params, "fields", [])] or [SignatureField(), SignatureField()]
    return [SignatureFieldsBlock(**_fields(spec), fields=fields, with_place_date=getattr(params, "with_place_date", True))]


def _attendance_sheet(spec, params, strings):
    return [AttendanceSheetBlock(**_fields(spec), names=[_t(strings, f"person{index}") for index in range(1, 7)], columns=list(getattr(params, "columns", []) or []), blank_rows=getattr(params, "blank_rows", 3))]


def _todo_table_block(spec, params, strings):
    return [TodoTableBlock(**_fields(spec), table=_todo_table(strings, 4))]


def _event_rows(strings: dict[str, str]) -> list[tuple[date, str]]:
    return [(date(2026, 4, 2), _t(strings, "event1")), (date(2026, 4, 18), _t(strings, "event2")), (date(2026, 5, 7), _t(strings, "event3"))]


def _event_table(spec, params, strings):
    columns = [TableColumn(key="date", label_key="col.date"), TableColumn(key="title", label_key="col.title", width="fill"), TableColumn(key="location", label_key="col.location")]
    rows = [TableRow(cells=[_text(format_date(day)), _text(title), _text(_t(strings, "place"))]) for day, title in _event_rows(strings)]
    return [EventTableBlock(**_fields(spec), table=TableData(columns=columns, groups=[TableGroup(rows=rows)]))]


def _event_calendar(spec, params, strings):
    events = {str(day.day): [CalendarEvent(title=title)] for day, title in _event_rows(strings) if day.month == 4}
    return [EventCalendarMonthBlock(**_fields(spec), months=[CalendarMonth(year=2026, month=4, first_weekday=2, days=30, events=events)])]


def _event_agenda(spec, params, strings):
    months: dict[int, list[AgendaItem]] = {}
    for day, title in _event_rows(strings):
        months.setdefault(day.month, []).append(AgendaItem(date=format_date(day), title=title, detail=_t(strings, "place")))
    return [EventAgendaBlock(**_fields(spec), months=[AgendaMonth(year=2026, month=month, items=items) for month, items in months.items()])]


def _list_table(spec, params, strings):
    columns = [TableColumn(key="column_one", label=_t(strings, "listColumn1"), width="fill"), TableColumn(key="column_two", label=_t(strings, "listColumn2"))]
    rows = [TableRow(cells=[_text(_t(strings, f"event{index}")), _text(_t(strings, f"person{index}"))]) for index in range(1, 4)]
    return [ListTableBlock(**_fields(spec), table=TableData(columns=columns, groups=[TableGroup(rows=rows)]))]


def _finance_balance(spec, params, strings):
    return [FinanceBalanceBlock(**_fields(spec), balances=[BalanceLine(name=_t(strings, f"account{index}"), amount=format_amount(1250.5 * index), currency="CHF") for index in range(1, 3)])]


def _amount_table(strings: dict[str, str], *, subtotal: bool) -> TableData:
    columns = [TableColumn(key="date", label_key="col.date"), TableColumn(key="text", label_key="col.description", width="fill"), TableColumn(key="amount", label_key="col.amount", align="right")]
    amounts = [120.0, -45.5, 380.0]
    rows = [TableRow(cells=[_text(format_date(date(2026, 3, index * 4))), _text(_t(strings, f"booking{index}")), Cell(k="amount", v=format_amount(amount))]) for index, amount in enumerate(amounts, start=1)]
    totals = [_text(""), _text(strings.get("label.total", "")), Cell(k="amount", v=format_amount(sum(amounts)))] if subtotal else None
    return TableData(columns=columns, groups=[TableGroup(rows=rows)], totals=totals)


def _finance_transactions(spec, params, strings):
    return [FinanceTransactionsBlock(**_fields(spec), table=_amount_table(strings, subtotal=True))]


def _fines(spec, params, strings):
    columns = [TableColumn(key="person", label_key="col.person", width="fill"), TableColumn(key="status", label_key="col.status"), TableColumn(key="amount", label_key="col.amount", align="right")]
    rows = [TableRow(cells=[_text(_t(strings, f"person{index}")), Cell(k="status", status="fineStatus.open" if index % 2 else "fineStatus.collected"), Cell(k="amount", v=format_amount(5 * index))]) for index in range(1, 4)]
    return [FinesBlock(**_fields(spec), table=TableData(columns=columns, groups=[TableGroup(rows=rows)]))]


def _kpis(spec, params, strings):
    values = {"sessions": "11", "attendanceRate": "86%", "openTodos": "3", "doneTodos": "17", "events": "27", "members": "24", "finesTotal": format_amount(85)}
    tiles = [KpiTile(label_key=f"kpi.{key}", value=values.get(key, "0")) for key in getattr(params, "tiles", ["sessions", "attendanceRate"])]
    return [KpiTilesBlock(**_fields(spec), tiles=tiles)]


def _chart(spec, params, strings):
    categories = [strings.get(f"month.{month}", str(month))[:3] for month in range(1, 7)]
    if getattr(params, "chart_type", "") in ("todos",):
        return [ChartBlock(**_fields(spec), kind="donut", categories=["", "", ""], category_keys=["todoStatus.open", "todoStatus.in_progress", "todoStatus.done"], category_tones=["warning", "info", "success"], series=[ChartSeries(values=[3, 2, 17])])]
    return [ChartBlock(**_fields(spec), kind="bar", categories=categories, series=[ChartSeries(label_key="attendanceStatus.present", values=[9, 11, 8, 10, 12, 9])])]


def _stat_table(spec, params, strings):
    columns = [TableColumn(key="name", label_key="col.name", width="fill"), TableColumn(key="present", label_key="attendanceStatus.present", align="right"), TableColumn(key="rate", label_key="col.rate", align="right")]
    rows = [TableRow(cells=[_text(_t(strings, f"person{index}")), Cell(k="amount", v=str(12 - index)), Cell(k="amount", v=f"{95 - index * 5}%")]) for index in range(1, 5)]
    return [StatTableBlock(**_fields(spec), table=TableData(columns=columns, groups=[TableGroup(rows=rows)]))]


SAMPLES: dict[str, SampleFn] = {
    "protocol_element": _protocol_element,
    "session_date": _session_date,
    "session_notes": _session_notes,
    "form": _form,
    "matrix": _matrix,
    "entry_exit": _entry_exit,
    "image": _image,
    "image_gallery": _gallery,
    "attendance": _attendance,
    "attendance_matrix": _attendance_matrix,
    "member_list": _member_list,
    "signature_fields": _signature_fields,
    "attendance_sheet": _attendance_sheet,
    "todo_table": _todo_table_block,
    "event_table": _event_table,
    "event_calendar_month": _event_calendar,
    "event_agenda": _event_agenda,
    "list_table": _list_table,
    "finance_balance": _finance_balance,
    "finance_transactions": _finance_transactions,
    "fines": _fines,
    "kpi_tiles": _kpis,
    "chart": _chart,
    "stat_table": _stat_table,
}


def sample_blocks(spec: BlockSpec, params: Any, strings: dict[str, str]) -> list[Any]:
    return SAMPLES[spec.type](spec, params, strings)


__all__ = ["SAMPLES", "sample_blocks", "BulletList"]
