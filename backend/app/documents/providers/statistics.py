"""Statistik: Kennzahlen, Diagramme (Datenreihen, gezeichnet in Typst), Statistiktabellen.

Alle Werte kommen aus statistics_common.py - derselben Quelle wie ``/statistics/overview`` -,
damit PDF und Dashboard nicht auseinanderlaufen. Finanz- und Bussendaten setzen das Feature
«Finanzen» voraus."""
from __future__ import annotations

from datetime import date

from sqlalchemy import func, select

from app.documents.catalog import BlockSpec, ChartParams, KpiTilesParams, StatTableParams
from app.documents.context import BuildContext, format_amount, format_number, format_percent
from app.documents.model import ChartBlock, ChartSeries, KpiTile, KpiTilesBlock, StatTableBlock, TableData, TableGroup, TableRow
from app.documents.providers.common import amount_cell, col, sort_key, spec_fields, text_cell
from app.documents.providers.people import resolve_period
from app.models import Event, Participant, Protocol
from app.services import statistics_common as stats

FINANCE_CHARTS = {"finance_by_month", "fines_by_participant", "fines_by_type"}
FINANCE_TABLES = {"fines_by_participant", "finance_by_month"}
FINANCE_TILES = {"finesTotal"}


def _month_label(value: str) -> str:
    """"2026-03" → "03/26" (sprachneutral)."""
    try:
        year, month = value.split("-")
        return f"{month}/{year[2:]}"
    except ValueError:
        return value


def _attendance(ctx: BuildContext, bounds):
    return stats.aggregate_attendance(stats.fetch_attendance_blocks(ctx.db, ctx.tenant_id, bounds))


def provide_chart(ctx: BuildContext, spec: BlockSpec, params: ChartParams):
    if params.chart_type in FINANCE_CHARTS:
        ctx.require("finance")
    bounds = resolve_period(ctx, params)
    kind = "bar"
    horizontal = False
    categories: list[str] = []
    category_keys: list[str | None] = []
    category_tones: list[str] = []
    series: list[ChartSeries] = []
    value_format = "number"
    chart = params.chart_type

    if chart == "attendance_over_time":
        monthly, _ = _attendance(ctx, bounds)
        months = sorted(monthly)
        categories = [_month_label(month) for month in months]
        kind = "stacked_bar"
        series = [
            ChartSeries(label_key=f"chart.{status}", values=[getattr(monthly[month], status) for month in months], tone=tone)
            for status, tone in (("present", "success"), ("late", "info"), ("excused", "warning"), ("absent", "danger"))
        ]
    elif chart == "attendance_by_participant":
        _, people = _attendance(ctx, bounds)
        top = sorted(people, key=lambda person: person.counts.total, reverse=True)[:15]
        categories = [person.name for person in top]
        kind, horizontal = "stacked_bar", True
        series = [
            ChartSeries(label_key=f"chart.{status}", values=[getattr(person.counts, status) for person in top], tone=tone)
            for status, tone in (("present", "success"), ("late", "info"), ("excused", "warning"), ("absent", "danger"))
        ]
    elif chart == "finance_by_month":
        rows = stats.fetch_finance_by_month(ctx.db, ctx.tenant_id, bounds)
        categories = [_month_label(row.month) for row in rows]
        value_format = "amount"
        series = [
            ChartSeries(label_key="chart.income", values=[float(row.income or 0) for row in rows], tone="success"),
            ChartSeries(label_key="chart.expenses", values=[float(row.expenses or 0) for row in rows], tone="danger"),
        ]
    elif chart == "fines_by_participant":
        # Beträge verschiedener Währungen nicht addieren (MAIN-BE-019 aus main): Hauptwährung.
        rows = _main_currency_rows(stats.fetch_fines_by_participant(ctx.db, ctx.tenant_id, bounds))
        rows = sorted(rows, key=lambda row: float(row.amount or 0), reverse=True)[:10]
        categories = [row.name for row in rows]
        horizontal = True
        value_format = "amount"
        series = [ChartSeries(label_key="chart.amount", values=[float(row.amount or 0) for row in rows], tone="primary")]
    elif chart == "fines_by_type":
        # Anzahl je Typ über alle Währungen (die Abfrage liefert je Typ und Währung eine Zeile).
        counts: dict[str, int] = {}
        for row in stats.fetch_fines_by_type(ctx.db, ctx.tenant_id, bounds):
            counts[row.fine_type] = counts.get(row.fine_type, 0) + int(row.count)
        kind = "donut"
        categories = list(counts)
        category_keys = [f"fineType.{fine_type}" if fine_type in ("late", "absent") else None for fine_type in counts]
        category_tones = ["warning" if fine_type == "late" else "danger" for fine_type in counts]
        series = [ChartSeries(label_key="chart.count", values=list(counts.values()))]
    elif chart == "todos":
        open_count, done_count = stats.aggregate_todo_counts(stats.fetch_todo_rows(ctx.db, ctx.tenant_id, bounds))
        kind = "donut"
        categories = ["done", "open"]
        category_keys = ["chart.done", "chart.open"]
        category_tones = ["success", "neutral"]
        series = [ChartSeries(label_key="chart.count", values=[done_count, open_count])]
    elif chart in ("groups_sessions", "groups_avg"):
        groups = stats.aggregate_group_rows(stats.fetch_group_session_rows(ctx.db, ctx.tenant_id, bounds), params.cycle_key)
        categories = [group["name"] for group in groups]
        horizontal = True
        if chart == "groups_sessions":
            series = [
                ChartSeries(label_key="chart.sessions", values=[group["sessions"] for group in groups], tone="secondary"),
                ChartSeries(label_key="chart.sessionsWithParticipants", values=[group["sessions_with_p"] for group in groups], tone="primary"),
            ]
        else:
            value_format = "decimal"
            series = [ChartSeries(label_key="chart.avgParticipants", values=[group["avg"] for group in groups], tone="secondary")]

    return [
        ChartBlock(
            **spec_fields(spec),
            kind=kind,
            horizontal=horizontal,
            categories=categories,
            category_keys=category_keys,
            category_tones=category_tones,
            series=series,
            value_format=value_format,
        )
    ]


def _protocol_count(ctx: BuildContext, bounds) -> int:
    statement = select(func.count(Protocol.id)).where(Protocol.tenant_id == ctx.tenant_id, Protocol.status.in_(["durchgeführt", "abgeschlossen"]))
    if bounds is not None:
        statement = statement.where(Protocol.protocol_date >= bounds[0], Protocol.protocol_date <= bounds[1])
    return int(ctx.db.scalar(statement) or 0)


def _event_count(ctx: BuildContext, bounds) -> int:
    statement = select(func.count(Event.id)).where(Event.tenant_id == ctx.tenant_id, Event.is_session_marker.is_(False), Event.is_cancelled.is_(False))
    if bounds is not None:
        statement = statement.where(Event.event_date >= bounds[0], Event.event_date <= bounds[1])
    return int(ctx.db.scalar(statement) or 0)


def provide_kpis(ctx: BuildContext, spec: BlockSpec, params: KpiTilesParams):
    bounds = resolve_period(ctx, params)
    tiles: list[KpiTile] = []
    todo_counts: tuple[int, int] | None = None
    for key in params.tiles:
        if key in FINANCE_TILES:
            ctx.require("finance")
        if key == "sessions":
            tiles.append(KpiTile(label_key="kpi.sessions", value=format_number(_protocol_count(ctx, bounds))))
        elif key == "attendanceRate":
            monthly, _ = _attendance(ctx, bounds)
            attended = sum(counts.present + counts.late for counts in monthly.values())
            total = sum(counts.total for counts in monthly.values())
            tiles.append(KpiTile(label_key="kpi.attendanceRate", value=format_percent(attended, total), tone="success"))
        elif key in ("openTodos", "doneTodos"):
            if todo_counts is None:
                todo_counts = stats.aggregate_todo_counts(stats.fetch_todo_rows(ctx.db, ctx.tenant_id, bounds))
            value = todo_counts[0] if key == "openTodos" else todo_counts[1]
            tiles.append(KpiTile(label_key=f"kpi.{key}", value=format_number(value), tone="warning" if key == "openTodos" else "success"))
        elif key == "events":
            tiles.append(KpiTile(label_key="kpi.events", value=format_number(_event_count(ctx, bounds))))
        elif key == "members":
            count = ctx.db.scalar(select(func.count(Participant.id)).where(Participant.tenant_id == ctx.tenant_id, Participant.is_active.is_(True))) or 0
            tiles.append(KpiTile(label_key="kpi.members", value=format_number(count)))
        elif key == "finesTotal":
            totals: dict[str, float] = {}
            for row in stats.fetch_fines_by_participant(ctx.db, ctx.tenant_id, bounds):
                totals[row.currency or ""] = totals.get(row.currency or "", 0.0) + float(row.amount or 0)
            value = " · ".join(f"{format_amount(total)} {code}".strip() for code, total in totals.items()) or format_amount(0)
            tiles.append(KpiTile(label_key="kpi.finesTotal", value=value))
    return [KpiTilesBlock(**spec_fields(spec), tiles=tiles)]


def provide_table(ctx: BuildContext, spec: BlockSpec, params: StatTableParams):
    if params.table in FINANCE_TABLES:
        ctx.require("finance")
    bounds = resolve_period(ctx, params)
    rows: list[TableRow] = []
    if params.table == "attendance_by_participant":
        _, people = _attendance(ctx, bounds)
        columns = [col("name", "col.name", width="fill")] + [col(status, f"attendanceStatus.{status}", align="right") for status in ("present", "late", "excused", "absent")] + [col("rate", "col.rate", align="right")]
        for person in sorted(people, key=lambda item: sort_key(item.name)):
            counts = person.counts
            rows.append(TableRow(cells=[text_cell(person.name), *(amount_cell(str(getattr(counts, status))) for status in ("present", "late", "excused", "absent")), amount_cell(format_percent(counts.present + counts.late, counts.total))]))
    elif params.table == "fines_by_participant":
        columns = [col("name", "col.person", width="fill"), col("count", "col.count", align="right"), col("amount", "col.amount", align="right")]
        for row in sorted(stats.fetch_fines_by_participant(ctx.db, ctx.tenant_id, bounds), key=lambda item: float(item.amount or 0), reverse=True):
            rows.append(TableRow(cells=[text_cell(row.name), amount_cell(str(int(row.count))), amount_cell(f"{format_amount(row.amount)} {row.currency or ''}".strip())]))
    elif params.table == "groups":
        columns = [col("group", "col.group", width="fill"), col("sessions", "col.sessions", align="right"), col("with", "col.sessionsWithParticipants", align="right"), col("avg", "col.avgParticipants", align="right")]
        for group in stats.aggregate_group_rows(stats.fetch_group_session_rows(ctx.db, ctx.tenant_id, bounds)):
            rows.append(TableRow(cells=[text_cell(group["name"]), amount_cell(str(group["sessions"])), amount_cell(str(group["sessions_with_p"])), amount_cell(format_number(group["avg"], 1))]))
    else:
        columns = [col("month", "col.month"), col("income", "col.income", align="right"), col("expenses", "col.expenses", align="right"), col("balance", "col.balance", align="right", width="fill")]
        for row in stats.fetch_finance_by_month(ctx.db, ctx.tenant_id, bounds):
            income, expenses = float(row.income or 0), float(row.expenses or 0)
            rows.append(TableRow(cells=[text_cell(_month_label(row.month)), amount_cell(format_amount(income)), amount_cell(format_amount(expenses)), amount_cell(format_amount(income - expenses, sign=True))]))
    table = TableData(columns=columns, groups=[TableGroup(rows=rows)] if rows else [])
    return [StatTableBlock(**spec_fields(spec), table=table)]


def default_period(today: date) -> tuple[date, date]:
    return date(today.year, 1, 1), date(today.year, 12, 31)


def _main_currency_rows(rows):
    """Zeilen der Währung mit den meisten Bussen (Diagramme zeigen nur eine Währung)."""
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.currency or ""] = counts.get(row.currency or "", 0) + int(row.count)
    if not counts:
        return []
    main = max(counts, key=lambda code: (counts[code], code))
    return [row for row in rows if (row.currency or "") == main]

