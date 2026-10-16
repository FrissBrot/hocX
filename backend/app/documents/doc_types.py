"""Dokumenttypen: Standard-Zusammenstellungen aus dem Block-Katalog.

Ein Dokumenttyp ist nur ein Startpunkt: der Export-Dialog übernimmt seine Blöcke, der Benutzer
kann sie frei ändern und als Rezept speichern."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.documents.catalog import BlockSpec


@dataclass(frozen=True)
class DocumentType:
    key: str
    blocks: list[BlockSpec] = field(default_factory=list)
    # Typ braucht ein Protokoll im Kontext (Protokoll, Einladung)
    needs_protocol: bool = False
    # Für Mehrseiter mit vielen Spalten sinnvoll
    orientation: str = "portrait"


def document_types(today: date | None = None) -> dict[str, DocumentType]:
    today = today or date.today()
    year_start, year_end = date(today.year, 1, 1).isoformat(), date(today.year, 12, 31).isoformat()
    types = [
        DocumentType("protocol", [BlockSpec(type="protocol_element")], needs_protocol=True),
        DocumentType(
            "invitation",
            [
                BlockSpec(type="session_date"),
                BlockSpec(type="richtext", params={"markdown": ""}),
                BlockSpec(type="protocol_element", params={"titles_only": True}),
                BlockSpec(type="event_table", params={"date_from": today.isoformat(), "columns": ["date", "title", "location"]}),
            ],
            needs_protocol=True,
        ),
        DocumentType("todos", [BlockSpec(type="todo_table", params={"status": "open", "group_by": "person", "columns": ["status", "due", "protocol"]})]),
        DocumentType("events", [BlockSpec(type="event_agenda", params={"date_from": year_start, "date_to": year_end})]),
        DocumentType("attendance_sheet", [BlockSpec(type="session_date"), BlockSpec(type="attendance_sheet")]),
        DocumentType("members", [BlockSpec(type="member_list")]),
        DocumentType(
            "finance",
            [
                BlockSpec(type="finance_balance", params={"as_of": year_end}),
                BlockSpec(type="stat_table", params={"table": "finance_by_month", "date_from": year_start, "date_to": year_end}),
                BlockSpec(type="chart", params={"chart_type": "finance_by_month", "date_from": year_start, "date_to": year_end}),
            ],
        ),
        DocumentType(
            "statistics",
            [
                BlockSpec(type="kpi_tiles", params={"date_from": year_start, "date_to": year_end}),
                BlockSpec(type="chart", params={"chart_type": "attendance_over_time", "date_from": year_start, "date_to": year_end}),
                BlockSpec(type="stat_table", params={"table": "attendance_by_participant", "date_from": year_start, "date_to": year_end}),
                BlockSpec(type="chart", params={"chart_type": "todos", "date_from": year_start, "date_to": year_end}),
                BlockSpec(type="chart", params={"chart_type": "groups_sessions", "date_from": year_start, "date_to": year_end}),
            ],
        ),
        DocumentType("list", [BlockSpec(type="list_table")]),
        DocumentType("custom", []),
    ]
    return {item.key: item for item in types}


DOCUMENT_TYPE_KEYS: tuple[str, ...] = tuple(document_types(date(2000, 1, 1)).keys())
