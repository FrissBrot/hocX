"""Listen-Abgaben: Die Bezeichnung eines Listeneintrags kommt aus der Spalte mit der Rolle
«Bezeichnung» (list_column, Migration 0186), sonst aus der ersten Text- oder Termin-Spalte -
dieselbe Regel wie im Haupt-Backend (app/services/list_columns.py::label_column)."""
import uuid

from app import element_resolver, repository

COLUMNS = [
    {"id": 1, "list_definition_id": 9, "key": "k-pers", "value_type": "participants", "sort_index": 10},
    {"id": 2, "list_definition_id": 9, "key": "k-amt", "value_type": "text", "sort_index": 20},
    {"id": 3, "list_definition_id": 9, "key": "k-ort", "value_type": "text", "sort_index": 30},
]
ENTRY = {"id": 5, "public_id": uuid.uuid4(), "list_definition_id": 9, "sort_index": 0,
         "values_json": {"k-pers": {"participant_ids": []}, "k-amt": {"text_value": "Kochen"}, "k-ort": {"text_value": "Küche"}}}


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self._rows


class _Db:
    def execute(self, _statement):
        return _Rows(COLUMNS)


def _labels(monkeypatch, label_column_id):
    definition = {"id": 9, "tenant_id": 1, "name": "Ämtli", "label_column_id": label_column_id, "is_active": True}
    monkeypatch.setattr(repository, "latest_status_by_element", lambda *a, **k: {})
    monkeypatch.setattr(repository, "count_files_by_element", lambda *a, **k: {})
    monkeypatch.setattr(repository, "get_list_definition", lambda *a, **k: definition)
    monkeypatch.setattr(repository, "list_list_entries", lambda *a, **k: [ENTRY])
    monkeypatch.setattr(repository, "get_participants", lambda *a, **k: {})
    monkeypatch.setattr(repository, "get_events", lambda *a, **k: {})
    assignment = {"id": 1, "source_type": "list", "list_definition_id": 9, "deadline": None, "sort_order": "manual", "title": "Ämtli"}
    return [element["label"] for element in element_resolver.resolve_open_elements(_Db(), assignment)]


def test_label_role_wins(monkeypatch):
    assert _labels(monkeypatch, label_column_id=3) == ["Küche"]


def test_without_role_first_text_column(monkeypatch):
    assert _labels(monkeypatch, label_column_id=None) == ["Kochen"]
