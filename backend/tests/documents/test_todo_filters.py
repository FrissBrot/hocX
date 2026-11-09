"""Filter der Pendenzen-Tabelle (Export-Dialog): Status, überfällig, Fälligkeit mit/ohne Datum.

Der Export-Dialog rechnet dieselben Filter im Browser nach (todo-export-filters.ts); beide
müssen übereinstimmen, sonst stimmt die Auswahl nicht mit dem Export überein."""
from __future__ import annotations

import uuid
from datetime import date
from types import SimpleNamespace

from app.documents.catalog import TodoTableParams
from app.documents.providers.todos import filter_rows, is_overdue

TODAY = date(2026, 11, 9)
CTX = SimpleNamespace(today=TODAY)


def _row(name: str, status: str = "open", due: date | None = None, tags: list[str] | None = None):
    return SimpleNamespace(
        name=name,
        todo_status_code=status,
        resolved_due_date=due,
        ProtocolTodo=SimpleNamespace(public_id=uuid.uuid4(), task=name, tags=tags or [], assigned_participant_id=None),
    )


ROWS = [
    _row("überfällig", due=date(2026, 11, 5)),
    _row("heute", due=TODAY),
    _row("später", due=date(2026, 12, 1)),
    _row("ohne Datum"),
    _row("in Arbeit überfällig", status="in_progress", due=date(2026, 10, 30)),
    _row("erledigt überfällig", status="done", due=date(2026, 10, 1)),
]


def names(params: TodoTableParams) -> list[str]:
    return [row.name for row in filter_rows(CTX, list(ROWS), params)]


def test_overdue_is_open_and_strictly_before_today():
    assert is_overdue(ROWS[0], TODAY)
    assert not is_overdue(ROWS[1], TODAY)  # heute fällig ist noch nicht überfällig
    assert not is_overdue(ROWS[3], TODAY)
    assert not is_overdue(ROWS[5], TODAY)  # erledigt


def test_overdue_only():
    assert names(TodoTableParams(overdue_only=True)) == ["überfällig", "in Arbeit überfällig"]
    assert names(TodoTableParams(status="all", overdue_only=True)) == ["überfällig", "in Arbeit überfällig"]


def test_status_in_progress_and_open():
    assert names(TodoTableParams(status="in_progress")) == ["in Arbeit überfällig"]
    assert "in Arbeit überfällig" in names(TodoTableParams(status="open"))
    assert names(TodoTableParams(status="done")) == ["erledigt überfällig"]


def test_due_until_with_and_without_undated():
    assert names(TodoTableParams(due_until=TODAY)) == ["überfällig", "heute", "ohne Datum", "in Arbeit überfällig"]
    assert names(TodoTableParams(due_until=TODAY, include_undated=False)) == ["überfällig", "heute", "in Arbeit überfällig"]
    # include_undated wirkt nur zusammen mit due_until
    assert "ohne Datum" in names(TodoTableParams(include_undated=False))


def test_exclude_ids_after_filters():
    params = TodoTableParams(overdue_only=True, exclude_ids=[ROWS[0].ProtocolTodo.public_id])
    assert names(params) == ["in Arbeit überfällig"]
