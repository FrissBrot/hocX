"""Termine: Tabelle (Spalten wie im Element-Editor), Monatskalender, Jahresprogramm.

Sichtbarkeit wie ``GET /api/events``: automatisch erzeugte «Nächster Hock»-Platzhalter ohne
Protokoll erscheinen nicht. Filter über den gemeinsamen Terminfilter (event_filter.py)."""
from __future__ import annotations

import calendar
from datetime import date
from sqlalchemy import exists, or_, select

from app.documents.catalog import BlockSpec, EventAgendaParams, EventCalendarParams, EventSelectionParams, EventTableParams
from app.documents.context import BuildContext, format_date, format_date_range
from app.documents.model import (
    AgendaItem,
    AgendaMonth,
    CalendarEvent,
    CalendarMonth,
    Cell,
    EventAgendaBlock,
    EventCalendarMonthBlock,
    EventTableBlock,
    TableColumn,
    TableData,
    TableGroup,
    TableRow,
    Tag,
)
from app.documents.providers.common import col, safe_color, spec_fields, split_tag_text, tags_cell, text_cell
from app.models import Event, Participant, Protocol, Tenant
from app.services.event_filter import default_event_filter, filter_events, normalize_event_filter, split_tags

EVENT_COLUMN_ORDER = ["date", "tag", "title", "description", "participant_count", "location", "organizers", "cancelled"]


def tenant_events(ctx: BuildContext) -> list[Event]:
    has_protocol = exists().where(Protocol.event_id == Event.id)
    return list(
        ctx.db.scalars(
            select(Event)
            .where(Event.tenant_id == ctx.tenant_id, or_(Event.is_session_marker.is_(False), has_protocol))
            .order_by(Event.event_date.asc(), Event.id.asc())
        )
    )


def tag_config(ctx: BuildContext) -> dict:
    tenant = ctx.db.get(Tenant, ctx.tenant_id)
    return (tenant.tag_config_json or {}) if tenant is not None else {}


def select_events(ctx: BuildContext, params: EventSelectionParams, *, default_range_mode: str = "all") -> list[Event]:
    events = tenant_events(ctx)
    if params.event_filter:
        normalized = normalize_event_filter(params.event_filter, default_range_mode=default_range_mode)
        selected = filter_events(ctx.db, events, normalized, protocol=ctx.reference_protocol())
    else:
        event_filter = default_event_filter(range_mode="all")
        if params.tags:
            event_filter["tags"] = split_tags(params.tags)
        selected = filter_events(ctx.db, events, event_filter, protocol=ctx.reference_protocol())
        if params.date_from is not None:
            selected = [event for event in selected if (event.event_end_date or event.event_date) >= params.date_from]
        if params.date_to is not None:
            selected = [event for event in selected if event.event_date <= params.date_to]
    if not params.include_cancelled:
        selected = [event for event in selected if not event.is_cancelled]
    return selected


def organizer_names(ctx: BuildContext, events: list[Event]) -> dict[int, str]:
    ids = {int(pid) for event in events for pid in (event.organizer_ids or []) if str(pid).isdigit()}
    if not ids:
        return {}
    names = dict(
        ctx.db.execute(select(Participant.id, Participant.display_name).where(Participant.id.in_(ids), Participant.tenant_id == ctx.tenant_id)).all()
    )
    return {
        event.id: ", ".join(names[int(pid)] for pid in (event.organizer_ids or []) if str(pid).isdigit() and int(pid) in names)
        for event in events
    }


def event_columns(columns: list[str]) -> list[TableColumn]:
    wanted = [key for key in EVENT_COLUMN_ORDER if key in columns]
    content_keys = {"date", "tag", "title", "description", "participant_count"}
    if not any(key in content_keys for key in wanted):
        wanted.insert(0, "title")
    labels = {
        "date": ("col.date", "left", "auto"),
        "tag": ("col.tags", "left", "auto"),
        "title": ("col.title", "left", "fill"),
        "description": ("col.description", "left", "fill"),
        "participant_count": ("col.participants", "right", "narrow"),
        "location": ("col.location", "left", "auto"),
        "organizers": ("col.organizers", "left", "auto"),
        "cancelled": ("col.cancelled", "left", "narrow"),
    }
    return [col(key, labels[key][0], align=labels[key][1], width=labels[key][2]) for key in wanted]


def event_table(
    ctx: BuildContext,
    events: list[Event],
    columns: list[str],
    *,
    gray_past: bool = True,
    show_tag_colors: bool = False,
    reference_date: date | None = None,
) -> TableData:
    table_columns = event_columns(columns)
    keys = [column.key for column in table_columns]
    organizers = organizer_names(ctx, events) if "organizers" in keys else {}
    config = tag_config(ctx) if show_tag_colors else {}
    rows: list[TableRow] = []
    for event in events:
        end = event.event_end_date or event.event_date
        cells: list[Cell] = []
        for key in keys:
            if key == "date":
                cells.append(text_cell(format_date_range(event.event_date, end)))
            elif key == "tag":
                cells.append(tags_cell(split_tag_text(event.tag), config) if show_tag_colors else text_cell(", ".join(split_tag_text(event.tag)) or "–"))
            elif key == "title":
                cells.append(text_cell(event.title, strike=bool(event.is_cancelled)))
            elif key == "description":
                cells.append(text_cell(event.description or "–"))
            elif key == "participant_count":
                cells.append(text_cell(max(0, int(event.participant_count or 0))))
            elif key == "location":
                cells.append(text_cell(event.location or "–"))
            elif key == "organizers":
                cells.append(text_cell(organizers.get(event.id) or "–"))
            elif key == "cancelled":
                cells.append(Cell(k="text", v="", note_key="label.cancelled") if event.is_cancelled else text_cell("–"))
        muted = bool(gray_past and reference_date and end < reference_date)
        rows.append(TableRow(cells=cells, muted=muted))
    return TableData(columns=table_columns, groups=[TableGroup(rows=rows)] if rows else [])


def provide_table(ctx: BuildContext, spec: BlockSpec, params: EventTableParams):
    events = select_events(ctx, params)
    table = event_table(ctx, events, list(params.columns), gray_past=params.gray_past, show_tag_colors=params.show_tag_colors, reference_date=ctx.reference_protocol().protocol_date)
    return [EventTableBlock(**spec_fields(spec), table=table)]


def _event_color(event: Event, config: dict) -> str | None:
    for tag in split_tag_text(event.tag):
        color = safe_color((config.get(tag) or {}).get("color"))
        if color:
            return color
    return None


def calendar_months(events: list[Event], config: dict, *, start: date, end: date, reference_date: date) -> list[CalendarMonth]:
    months: list[CalendarMonth] = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month) and len(months) < 24:
        first_weekday, days = calendar.monthrange(year, month)
        by_day: dict[str, list[CalendarEvent]] = {}
        for event in events:
            event_end = event.event_end_date or event.event_date
            for day in range(1, days + 1):
                current = date(year, month, day)
                if event.event_date <= current <= event_end:
                    by_day.setdefault(str(day), []).append(
                        CalendarEvent(title=event.title, muted=event_end < reference_date, color=_event_color(event, config), cancelled=bool(event.is_cancelled))
                    )
        months.append(CalendarMonth(year=year, month=month, first_weekday=first_weekday, days=days, events=by_day))
        month += 1
        if month > 12:
            year, month = year + 1, 1
    return months


def provide_calendar(ctx: BuildContext, spec: BlockSpec, params: EventCalendarParams):
    events = select_events(ctx, params)
    reference = ctx.reference_protocol().protocol_date or ctx.today
    start = params.date_from or (min((event.event_date for event in events), default=None)) or reference
    end = params.date_to or (max(((event.event_end_date or event.event_date) for event in events), default=None)) or start
    if end < start:
        end = start
    months = calendar_months(events, tag_config(ctx), start=start, end=end, reference_date=reference) if events or params.date_from else []
    return [EventCalendarMonthBlock(**spec_fields(spec), months=months)]


def provide_agenda(ctx: BuildContext, spec: BlockSpec, params: EventAgendaParams):
    events = select_events(ctx, params)
    config = tag_config(ctx)
    reference = ctx.reference_protocol().protocol_date or ctx.today
    months: dict[tuple[int, int], AgendaMonth] = {}
    for event in events:
        key = (event.event_date.year, event.event_date.month)
        month = months.setdefault(key, AgendaMonth(year=key[0], month=key[1]))
        end = event.event_end_date or event.event_date
        date_label = event.event_date.strftime("%d.%m.") if end == event.event_date else f"{event.event_date.strftime('%d.%m.')}–{end.strftime('%d.%m.')}"
        month.items.append(
            AgendaItem(
                date=date_label,
                title=event.title,
                detail=event.location if params.show_location and event.location else None,
                tags=[Tag(label=tag, color=safe_color((config.get(tag) or {}).get("color"))) for tag in split_tag_text(event.tag)],
                muted=end < reference,
                cancelled=bool(event.is_cancelled),
            )
        )
    return [EventAgendaBlock(**spec_fields(spec), months=[months[key] for key in sorted(months)])]


def ics(events: list[Event], *, tenant_name: str) -> str:
    """Termine als iCalendar (ganztägig, wie in der App erfasst)."""
    from datetime import UTC, datetime, timedelta

    def escape(value: str) -> str:
        return str(value or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//hocX//Dokument-Engine//DE", f"X-WR-CALNAME:{escape(tenant_name)}"]
    for event in events:
        end = (event.event_end_date or event.event_date) + timedelta(days=1)
        lines += [
            "BEGIN:VEVENT",
            f"UID:{event.public_id}@hocx",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{event.event_date.strftime('%Y%m%d')}",
            f"DTEND;VALUE=DATE:{end.strftime('%Y%m%d')}",
            f"SUMMARY:{escape(event.title)}",
        ]
        if event.description:
            lines.append(f"DESCRIPTION:{escape(event.description)}")
        if event.location:
            lines.append(f"LOCATION:{escape(event.location)}")
        if event.is_cancelled:
            lines.append("STATUS:CANCELLED")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def event_inline_label(event: Event, row_config: dict | None = None) -> str:
    """Ein Termin in einer Matrixzelle «Mehrere Termine» (Felder wie im Editor)."""
    config = row_config or {}
    parts: list[str] = []
    if config.get("event_show_date", True) is not False:
        parts.append(format_date_range(event.event_date, event.event_end_date))
    if config.get("event_show_title", False) is True:
        parts.append(event.title)
    if config.get("event_show_location", False) is True and event.location:
        parts.append(event.location)
    label = " ".join(parts)
    if config.get("event_show_description", True) is not False and event.description:
        label += f" ({event.description})"
    return label.strip()


def event_short_label(event: Event) -> str:
    return f"{format_date_range(event.event_date, event.event_end_date)} – {event.title}"
