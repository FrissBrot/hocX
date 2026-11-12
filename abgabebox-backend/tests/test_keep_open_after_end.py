"""Option «nach dem Enddatum offen halten» (submission_assignment.keep_open_after_end, 0173) und
Fensterende ab dem letzten Tag des Termins (wie die Fälligkeit der Pendenz im Hauptbackend)."""
from __future__ import annotations

from datetime import date, timedelta

from app import element_resolver, repository


def _stub(monkeypatch, *, status=None, events=()):
    statuses = {(None, None): status} if status else {}
    monkeypatch.setattr(repository, "latest_status_by_element", lambda db, assignment_id: statuses)
    monkeypatch.setattr(repository, "count_files_by_element", lambda db, assignment_id: {})
    monkeypatch.setattr(repository, "list_events_by_tag", lambda db, **kwargs: list(events))


def _manual(**overrides) -> dict:
    return {"id": 1, "tenant_id": 1, "title": "Bericht", "source_type": "manual", "sort_order": "date",
            "deadline": date.today() - timedelta(days=3), **overrides}


def test_past_deadline_closes_without_option(monkeypatch):
    _stub(monkeypatch)
    assert element_resolver.resolve_open_elements(None, _manual()) == []


def test_past_deadline_stays_open_with_option_until_closed(monkeypatch):
    _stub(monkeypatch)
    assert len(element_resolver.resolve_open_elements(None, _manual(keep_open_after_end=True))) == 1
    # Normale Kriterien gelten weiter: geschlossen (von Hand oder auto_close) ist geschlossen
    _stub(monkeypatch, status="closed")
    assert element_resolver.resolve_open_elements(None, _manual(keep_open_after_end=True)) == []


def _event_assignment(**overrides) -> dict:
    return {"id": 2, "tenant_id": 1, "title": "Lagerberichte", "source_type": "events", "sort_order": "date",
            "tag_filter": "Lager", "offset_days_before": 0, "offset_days_after": 2, "cycle_config_id": None, **overrides}


def test_window_ends_after_the_last_day_of_a_multi_day_event(monkeypatch):
    today = date.today()
    # Lager vom 5. bis gestern: Fenster endet erst 2 Tage nach dem letzten Lagertag
    event = {"id": 9, "public_id": "e9", "title": "Sommerlager", "event_date": today - timedelta(days=5), "event_end_date": today - timedelta(days=1)}
    _stub(monkeypatch, events=[event])
    [element] = element_resolver.resolve_open_elements(None, _event_assignment())
    assert element["window_end"] == (today + timedelta(days=1)).isoformat()


def test_event_window_past_end_with_option(monkeypatch):
    today = date.today()
    event = {"id": 9, "public_id": "e9", "title": "Hock", "event_date": today - timedelta(days=10), "event_end_date": None}
    _stub(monkeypatch, events=[event])
    assert element_resolver.resolve_open_elements(None, _event_assignment()) == []
    assert len(element_resolver.resolve_open_elements(None, _event_assignment(keep_open_after_end=True))) == 1
