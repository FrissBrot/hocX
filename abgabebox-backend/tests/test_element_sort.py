"""Regression tests for element_resolver._sort_elements - the ordering applied to elements in
the public Abgabebox, configured via SubmissionAssignment.sort_order in the hocX admin tool and
carried over unchanged here (not adjustable in this public-facing app, see the 2026-08-17
"Abgaben ohne Zeitfenster" feature). Pure function, no DB needed - the equivalent window/status
resolution logic (which does need a DB) is covered on the main backend's side in
backend/tests/test_submission_service.py, since both services intentionally duplicate this logic
(see this module's own docstring) rather than sharing a package.
"""
from __future__ import annotations

from datetime import date, timedelta

from app.element_resolver import _sort_elements


def _el(ref: str, label: str) -> dict:
    return {"element_ref": ref, "label": label}


def test_alphabetical_ignores_case_and_original_order():
    elements = [_el("c", "zebra"), _el("a", "Anfang"), _el("b", "mitte")]

    result = _sort_elements(elements, "alphabetical", {})

    assert [e["label"] for e in result] == ["Anfang", "mitte", "zebra"]


def test_date_orders_chronologically_and_puts_dateless_last():
    today = date.today()
    elements = [_el("later", "Spaeter"), _el("none", "Ohne Datum"), _el("earlier", "Frueher")]
    sort_dates = {
        "later": today + timedelta(days=30),
        "none": None,
        "earlier": today - timedelta(days=30),
    }

    result = _sort_elements(elements, "date", sort_dates)

    assert [e["element_ref"] for e in result] == ["earlier", "later", "none"]


def test_proximity_orders_by_closeness_to_today_and_puts_dateless_last():
    today = date.today()
    elements = [_el("far", "Weit weg"), _el("none", "Ohne Datum"), _el("close", "Nah"), _el("exact", "Heute")]
    sort_dates = {
        "far": today + timedelta(days=30),
        "none": None,
        "close": today - timedelta(days=2),
        "exact": today,
    }

    result = _sort_elements(elements, "proximity", sort_dates)

    assert [e["element_ref"] for e in result] == ["exact", "close", "far", "none"]


def test_sort_is_stable_on_ties():
    today = date.today()
    elements = [_el("x", "X"), _el("y", "Y"), _el("z", "Z")]
    sort_dates = {"x": today, "y": today, "z": today}

    result = _sort_elements(elements, "proximity", sort_dates)

    assert [e["element_ref"] for e in result] == ["x", "y", "z"]
