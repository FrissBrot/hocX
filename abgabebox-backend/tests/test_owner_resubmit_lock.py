"""«Nach dem Zurückziehen nur über den persönlichen Link» (Migration 0182): die Abgabebox blendet
Elemente mit zurückgezogenen Dateien aus, solange die Option gilt. Repository gestubbt."""
from __future__ import annotations

from app import element_resolver, repository


def _assignment(**overrides) -> dict:
    return {"id": 7, "tenant_id": 1, "title": "Bericht", "source_type": "manual", "deadline": None, "sort_order": "date", **overrides}


def _stub(monkeypatch, withdrawn: set):
    calls = []
    monkeypatch.setattr(repository, "latest_status_by_element", lambda db, assignment_id: {})
    monkeypatch.setattr(repository, "count_files_by_element", lambda db, assignment_id: {})
    # Einzelabgabe mit dem Standard-Element «manual» (Migration 0198)
    monkeypatch.setattr(repository, "list_manual_elements", lambda db, assignment_id: [
        {"id": 1, "public_id": None, "is_default": True, "name": "Bericht", "window_start": None, "window_end": None, "sort_index": 0},
    ])

    def withdrawn_elements(db, assignment_id):
        calls.append(assignment_id)
        return withdrawn

    monkeypatch.setattr(repository, "withdrawn_elements", withdrawn_elements)
    return calls


def test_withdrawn_element_is_locked_only_with_the_option(monkeypatch):
    calls = _stub(monkeypatch, {(None, None, None)})
    assert len(element_resolver.resolve_open_elements(None, _assignment())) == 1
    assert calls == []  # ohne Option keine zusätzliche Abfrage
    assert element_resolver.resolve_open_elements(None, _assignment(owner_resubmit_only_personal=True)) == []
    assert element_resolver.resolve_single_element(None, _assignment(owner_resubmit_only_personal=True), "manual") is None


def test_other_elements_stay_open(monkeypatch):
    _stub(monkeypatch, {(99, None, None)})
    assert len(element_resolver.resolve_open_elements(None, _assignment(owner_resubmit_only_personal=True))) == 1
