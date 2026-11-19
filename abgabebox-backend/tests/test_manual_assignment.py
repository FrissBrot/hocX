"""Einzelabgaben (source_type 'manual', weder Termine noch Liste): von Hand angelegte Elemente mit
eigenem Zeitfenster (Migration 0198). Das Standard-Element behält die Referenz «manual» und den
Einreichungs-Schlüssel ohne Ziel, alle weiteren heissen «manual-<public_id>». Das Gegenstueck zur
Hauptbackend-Logik (SubmissionService._resolve_raw_elements) wird hier bewusst dupliziert, siehe
Docstring von app.element_resolver. Das Repository wird gestubbt, es braucht keine DB."""
from __future__ import annotations

import uuid
from datetime import timedelta

from app import element_resolver, repository

EXTRA_ID = uuid.UUID("01900000-0000-7000-8000-000000000042")


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


def _element(*, id: int, name: str, default: bool = False, start=None, end=None, sort_index: int = 0) -> dict:
    return {
        "id": id, "public_id": EXTRA_ID if not default else uuid.uuid4(), "tenant_id": 1, "assignment_id": 7,
        "is_default": default, "name": name, "window_start": start, "window_end": end, "sort_index": sort_index,
    }


def _stub_repository(monkeypatch, *, elements=None, statuses=None, counts=None):
    elements = elements if elements is not None else [_element(id=1, name="Vereinsfotos", default=True)]
    monkeypatch.setattr(repository, "list_manual_elements", lambda db, assignment_id: elements)
    monkeypatch.setattr(repository, "latest_status_by_element", lambda db, assignment_id: statuses or {})
    monkeypatch.setattr(repository, "count_files_by_element", lambda db, assignment_id: counts or {})


def test_default_element_keeps_the_manual_ref_and_the_key_without_target(monkeypatch):
    _stub_repository(monkeypatch, counts={(None, None, None): 2})

    elements = element_resolver.resolve_open_elements(None, _assignment())

    assert elements == [
        {
            "element_ref": "manual",
            "event_id": None,
            "list_entry_id": None,
            "manual_element_id": None,
            "label": "Vereinsfotos",
            "window_start": None,
            "window_end": None,
            "uploaded_count": 2,
        }
    ]


def test_several_elements_each_with_own_ref_count_and_order(monkeypatch):
    elements = [
        _element(id=1, name="Anmeldung", default=True, sort_index=0),
        _element(id=42, name="Fotos", sort_index=1),
    ]
    _stub_repository(monkeypatch, elements=elements, counts={(None, None, None): 1, (None, None, 42): 3})

    result = element_resolver.resolve_open_elements(None, _assignment())

    assert [(e["element_ref"], e["label"], e["manual_element_id"], e["uploaded_count"]) for e in result] == [
        ("manual", "Anmeldung", None, 1),
        (f"manual-{EXTRA_ID}", "Fotos", 42, 3),
    ]
    assert element_resolver.resolve_single_element(None, _assignment(), f"manual-{EXTRA_ID}")["label"] == "Fotos"


def test_closed_element_is_hidden_the_others_stay_open(monkeypatch):
    elements = [_element(id=1, name="Anmeldung", default=True), _element(id=42, name="Fotos", sort_index=1)]
    _stub_repository(monkeypatch, elements=elements, statuses={(None, None, 42): "closed", (None, None, None): "submitted"})

    assert [e["label"] for e in element_resolver.resolve_open_elements(None, _assignment())] == ["Anmeldung"]


def test_each_element_honours_its_own_window(monkeypatch):
    today = element_resolver.local_today()
    elements = [
        _element(id=1, name="Vorbei", default=True, end=today - timedelta(days=1)),
        _element(id=42, name="Läuft", end=today + timedelta(days=1), sort_index=1),
        _element(id=43, name="Noch nicht", start=today + timedelta(days=2), sort_index=2),
    ]
    _stub_repository(monkeypatch, elements=elements)

    open_elements = element_resolver.resolve_open_elements(None, _assignment())
    assert [e["label"] for e in open_elements] == ["Läuft"]
    assert open_elements[0]["window_end"] == (today + timedelta(days=1)).isoformat()
    # «Nach dem Ende offen halten» gilt je Element wie bei Terminen
    kept = element_resolver.resolve_open_elements(None, _assignment(keep_open_after_end=True))
    assert [e["label"] for e in kept] == ["Vorbei", "Läuft"]


def test_unknown_refs_do_not_resolve(monkeypatch):
    _stub_repository(monkeypatch)

    assert element_resolver.resolve_single_element(None, _assignment(), "manual")["label"] == "Vereinsfotos"
    assert element_resolver.resolve_single_element(None, _assignment(), "entry-1") is None
    assert element_resolver.resolve_single_element(None, _assignment(), f"manual-{uuid.uuid4()}") is None
