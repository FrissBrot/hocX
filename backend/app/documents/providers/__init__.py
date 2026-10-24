"""Provider pro Datenquelle. ``PROVIDERS`` ordnet jeder Fachkomponente des Katalogs ihre
Funktion ``(ctx, spec, params) -> list[Block]`` zu. Provider enthalten kein Layout."""
from __future__ import annotations

from app.documents.providers import events, finance, lists, people, protocol, statistics, structure, todos

PROVIDERS = {
    "protocol_element": protocol.provide_protocol_element,
    "session_date": protocol.provide_session_date,
    "session_notes": protocol.provide_session_notes,
    "form": structure.form,
    "matrix": protocol.provide_matrix,
    "entry_exit": people.provide_entry_exit,
    "image": protocol.provide_image,
    "image_gallery": protocol.provide_image_gallery,
    "attendance": people.provide_attendance,
    "attendance_matrix": people.provide_attendance_matrix,
    "member_list": people.provide_member_list,
    "signature_fields": structure.signature_fields,
    "attendance_sheet": people.provide_attendance_sheet,
    "todo_table": todos.provide,
    "event_table": events.provide_table,
    "event_calendar_month": events.provide_calendar,
    "event_agenda": events.provide_agenda,
    "list_table": lists.provide,
    "finance_balance": finance.provide_balance,
    "finance_transactions": finance.provide_transactions,
    "fines": finance.provide_fines,
    "kpi_tiles": statistics.provide_kpis,
    "chart": statistics.provide_chart,
    "stat_table": statistics.provide_table,
}
