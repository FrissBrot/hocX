"""Manuelle Abgaben (source_type 'manual', weder Termine noch Liste): genau ein Element, das wie
die Abgabe heisst. Das Gegenstueck zur Hauptbackend-Logik (SubmissionService._resolve_raw_elements)
wird hier bewusst dupliziert, siehe Docstring von app.element_resolver. Das Repository wird
gestubbt, es braucht keine DB."""
from __future__ import annotations

from datetime import date, timedelta

from app import element_resolver, repository


def _assignment(**overrides) -> dict:
    base = {
        "id": 7,
        "tenant_id": 1,
        "title": "Vereinsfotos",
        "source_type": "manual",
        "deadline": None,
        "sort_order": "date",
    }
    return {**base, **overrides}


def _stub_repository(monkeypatch, *, status=None, file_count=0):
    statuses = {(None, None): status} if status else {}
    monkeypatch.setattr(repository, "latest_status_by_element", lambda db, assignment_id: statuses)
    monkeypatch.setattr(repository, "count_files_by_element", lambda db, assignment_id: {(None, None): file_count})


def test_manual_assignment_has_exactly_one_element_named_like_the_assignment(monkeypatch):
    _stub_repository(monkeypatch, file_count=2)

    elements = element_resolver.resolve_open_elements(None, _assignment())

    assert elements == [
        {
            "element_ref": "manual",
            "event_id": None,
            "list_entry_id": None,
            "label": "Vereinsfotos",
            "window_start": None,
            "window_end": None,
            "uploaded_count": 2,
        }
    ]


def test_manual_assignment_is_hidden_once_closed(monkeypatch):
    _stub_repository(monkeypatch, status="closed")

    assert element_resolver.resolve_open_elements(None, _assignment()) == []


def test_manual_assignment_stays_open_after_a_submission(monkeypatch):
    _stub_repository(monkeypatch, status="submitted", file_count=1)

    assert len(element_resolver.resolve_open_elements(None, _assignment())) == 1


def test_manual_assignment_honours_an_optional_deadline(monkeypatch):
    _stub_repository(monkeypatch)
    tomorrow = date.today() + timedelta(days=1)
    yesterday = date.today() - timedelta(days=1)

    open_elements = element_resolver.resolve_open_elements(None, _assignment(deadline=tomorrow))
    expired = element_resolver.resolve_open_elements(None, _assignment(deadline=yesterday))

    assert open_elements[0]["window_end"] == tomorrow.isoformat()
    assert expired == []


def test_single_element_lookup_resolves_the_manual_ref(monkeypatch):
    _stub_repository(monkeypatch)

    assert element_resolver.resolve_single_element(None, _assignment(), "manual")["label"] == "Vereinsfotos"
    assert element_resolver.resolve_single_element(None, _assignment(), "entry-1") is None
