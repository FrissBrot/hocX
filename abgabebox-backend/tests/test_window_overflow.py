"""Zeitfenster mit Altbeständen am Rand des Datumsbereichs (Nachtlauf 2026-11-20).

Das Hauptbackend klemmt Termin-Datum ± Offset seit 3f44486b an date.min/date.max
(submission_service._shift_date): Offsets vor der Schema-Grenze 0..3650 und Termine vor der
Datumsgrenze 1900–2999 existieren noch. Die Abgabebox dupliziert die Fensterlogik bewusst und
lief bei solchen Altbeständen in einen OverflowError: die öffentliche Abgabe antwortete mit 500,
auch für alle anderen Termine derselben Abgabe."""
from __future__ import annotations

from datetime import date, timedelta

from app import element_resolver, repository


def _stub(monkeypatch, events):
    monkeypatch.setattr(repository, "latest_status_by_element", lambda db, assignment_id: {})
    monkeypatch.setattr(repository, "count_files_by_element", lambda db, assignment_id: {})
    monkeypatch.setattr(repository, "list_events_by_tag", lambda db, **kwargs: list(events))


def _assignment(**overrides) -> dict:
    return {"id": 2, "tenant_id": 1, "title": "Berichte", "source_type": "events", "sort_order": "date",
            "tag_filter": "Hock", "offset_days_before": 7, "offset_days_after": 7, "cycle_config_id": None, **overrides}


def _event(event_id: int, day: date, end: date | None = None) -> dict:
    return {"id": event_id, "public_id": f"e{event_id}", "title": f"Hock {event_id}", "event_date": day, "event_end_date": end}


def test_huge_legacy_offset_keeps_the_assignment_reachable(monkeypatch):
    today = date.today()
    _stub(monkeypatch, [_event(1, today)])
    elements = element_resolver.resolve_open_elements(None, _assignment(offset_days_before=10**7, offset_days_after=10**7))
    assert [element["element_ref"] for element in elements] == ["event-e1"]
    assert elements[0]["window_start"] == date.min.isoformat()
    assert elements[0]["window_end"] == date.max.isoformat()


def test_legacy_event_at_the_end_of_the_calendar_does_not_break_other_events(monkeypatch):
    today = date.today()
    _stub(monkeypatch, [_event(1, today), _event(2, date.max - timedelta(days=1), date.max)])
    elements = element_resolver.resolve_open_elements(None, _assignment())
    assert [element["element_ref"] for element in elements] == ["event-e1"]
