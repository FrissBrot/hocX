"""Sichere, deklarative Bedingungen für Sichtbarkeitsregeln im Document Studio.

Eine Bedingung ist ein kleiner JSON-Baum, nie Code und nie ein Ausdruck, der geparst oder per
``eval`` ausgeführt wird. Operanden sind Bindungspfade (bindings.py) und literale Werte. Der
Evaluator bekommt eine Auflösungsfunktion Pfad → Wert; Pfade, die der Benutzer nicht lesen
darf, liefert die Auflösung gar nicht erst (siehe compiler.py), eine Bedingung kann also keine
Daten ausserhalb der Rechte des Exportierenden sichtbar machen.

Beispiel «nur wenn offene Aufgaben vorhanden sind»::

    {"op": "count", "path": "todos.open", "cmp": "gt", "value": 0}
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Callable, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

MAX_CONDITION_DEPTH = 6

_PATH = r"^[a-z][a-z0-9_]{0,40}(\.[a-z0-9_]{1,40}){0,4}$"
Scalar = Union[str, int, float, bool, None]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExistsCondition(_Strict):
    """Wert vorhanden (nicht leer) bzw. ``empty``: leer/fehlt."""

    op: Literal["exists", "empty"]
    path: str = Field(..., pattern=_PATH)


class CompareCondition(_Strict):
    op: Literal["eq", "ne", "gt", "gte", "lt", "lte", "contains"]
    path: str = Field(..., pattern=_PATH)
    value: Scalar = None


class InCondition(_Strict):
    op: Literal["in", "not_in"]
    path: str = Field(..., pattern=_PATH)
    values: list[Scalar] = Field(default_factory=list, max_length=50)


class CountCondition(_Strict):
    """Anzahl Elemente einer Listenbindung vergleichen."""

    op: Literal["count"]
    path: str = Field(..., pattern=_PATH)
    cmp: Literal["eq", "ne", "gt", "gte", "lt", "lte"] = "gt"
    value: int = Field(0, ge=0, le=100_000)


class GroupCondition(_Strict):
    op: Literal["all", "any"]
    items: list["Condition"] = Field(default_factory=list, max_length=20)


class NotCondition(_Strict):
    op: Literal["not"]
    item: "Condition"


Condition = Annotated[
    Union[ExistsCondition, CompareCondition, InCondition, CountCondition, GroupCondition, NotCondition],
    Field(discriminator="op"),
]

GroupCondition.model_rebuild()
NotCondition.model_rebuild()


class ConditionError(ValueError):
    pass


Resolver = Callable[[str], Any]


def is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, dict, set)):
        return len(value) == 0
    return False


def _normalize(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()[:10]
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        stripped = value.strip()
        try:
            return float(stripped) if stripped and stripped.replace(".", "", 1).lstrip("-").isdigit() else stripped.casefold()
        except ValueError:
            return stripped.casefold()
    return value


def _compare(cmp: str, left: Any, right: Any) -> bool:
    left, right = _normalize(left), _normalize(right)
    if cmp == "eq":
        return left == right
    if cmp == "ne":
        return left != right
    if left is None or right is None:
        return False
    try:
        if cmp == "gt":
            return left > right
        if cmp == "gte":
            return left >= right
        if cmp == "lt":
            return left < right
        if cmp == "lte":
            return left <= right
    except TypeError:
        # Unvergleichbare Typen (Text gegen Zahl) sind nie wahr, nie ein Fehler
        return False
    return False


def evaluate(condition: Any, resolve: Resolver, depth: int = 0) -> bool:
    """Wertet eine Bedingung aus. Unbekannte Pfade gelten als leer (nie ein Fehler)."""
    if condition is None:
        return True
    if depth > MAX_CONDITION_DEPTH:
        raise ConditionError("conditionTooDeep")
    op = condition.op
    if op in ("all", "any"):
        results = (evaluate(item, resolve, depth + 1) for item in condition.items)
        return all(results) if op == "all" else any(results)
    if op == "not":
        return not evaluate(condition.item, resolve, depth + 1)
    value = resolve(condition.path)
    if op == "exists":
        return not is_empty(value)
    if op == "empty":
        return is_empty(value)
    if op == "count":
        count = len(value) if isinstance(value, (list, tuple)) else (0 if is_empty(value) else 1)
        return _compare(condition.cmp, count, condition.value)
    if op == "contains":
        if isinstance(value, (list, tuple)):
            return any(_normalize(item) == _normalize(condition.value) for item in value)
        return str(condition.value or "").casefold() in str(value or "").casefold()
    if op in ("in", "not_in"):
        found = any(_normalize(value) == _normalize(candidate) for candidate in condition.values)
        return found if op == "in" else not found
    return _compare(op, value, condition.value)


def condition_paths(condition: Any) -> list[str]:
    """Alle Bindungspfade einer Bedingung (Validierung im Designer und im Compiler)."""
    if condition is None:
        return []
    if condition.op in ("all", "any"):
        return [path for item in condition.items for path in condition_paths(item)]
    if condition.op == "not":
        return condition_paths(condition.item)
    return [condition.path]
