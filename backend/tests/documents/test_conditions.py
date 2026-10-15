"""Sichere, deklarative Bedingungen (kein eval)."""
from __future__ import annotations

from datetime import date

import pytest
from pydantic import TypeAdapter, ValidationError

from app.documents.conditions import MAX_CONDITION_DEPTH, Condition, ConditionError, condition_paths, evaluate

ADAPTER = TypeAdapter(Condition)
VALUES = {
    "todos.open": [{"task": "a"}, {"task": "b"}],
    "todos.open_count": 2,
    "protocol.status_code": "held",
    "protocol.title": "Vorstand",
    "protocol.date": date(2026, 3, 1),
    "brand.toc": False,
    "empty.text": "  ",
}


def check(raw) -> bool:
    return evaluate(ADAPTER.validate_python(raw), VALUES.get)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ({"op": "count", "path": "todos.open", "cmp": "gt", "value": 0}, True),
        ({"op": "count", "path": "todos.open", "cmp": "eq", "value": 0}, False),
        ({"op": "exists", "path": "protocol.title"}, True),
        ({"op": "empty", "path": "empty.text"}, True),
        ({"op": "empty", "path": "gibt.es.nicht"}, True),
        ({"op": "eq", "path": "protocol.status_code", "value": "HELD"}, True),
        ({"op": "ne", "path": "protocol.status_code", "value": "closed"}, True),
        ({"op": "gte", "path": "todos.open_count", "value": "2"}, True),
        ({"op": "lt", "path": "todos.open_count", "value": 2}, False),
        ({"op": "gt", "path": "protocol.title", "value": 3}, False),
        ({"op": "eq", "path": "protocol.date", "value": "2026-03-01"}, True),
        ({"op": "eq", "path": "brand.toc", "value": False}, True),
        ({"op": "in", "path": "protocol.status_code", "values": ["held", "closed"]}, True),
        ({"op": "not_in", "path": "protocol.status_code", "values": ["held"]}, False),
        ({"op": "contains", "path": "protocol.title", "value": "vor"}, True),
        ({"op": "all", "items": [{"op": "exists", "path": "protocol.title"}, {"op": "eq", "path": "brand.toc", "value": True}]}, False),
        ({"op": "any", "items": [{"op": "exists", "path": "protocol.title"}, {"op": "eq", "path": "brand.toc", "value": True}]}, True),
        ({"op": "not", "item": {"op": "eq", "path": "brand.toc", "value": True}}, True),
    ],
)
def test_operators(raw, expected):
    assert check(raw) is expected


def test_invalid_structures_are_rejected():
    for raw in ({"op": "eval", "path": "x"}, {"op": "eq", "path": "__import__('os')"}, {"op": "eq", "path": "a.b", "extra": 1}):
        with pytest.raises(ValidationError):
            ADAPTER.validate_python(raw)


def test_depth_is_limited():
    raw: dict = {"op": "exists", "path": "a.b"}
    for _ in range(MAX_CONDITION_DEPTH + 2):
        raw = {"op": "not", "item": raw}
    with pytest.raises(ConditionError):
        check(raw)


def test_paths_are_collected():
    raw = {"op": "all", "items": [{"op": "exists", "path": "a.b"}, {"op": "not", "item": {"op": "count", "path": "c.d"}}]}
    assert condition_paths(ADAPTER.validate_python(raw)) == ["a.b", "c.d"]
