"""Terminfilter: PDF und Editor wählen dieselben Termine in derselben Reihenfolge.

Der Editor filtert in TypeScript (frontend/lib/element-types/event-filter.ts), das PDF in Python
(app/services/event_filter.py). Weichen die beiden ab, stehen im PDF Termine, die im Editor
weggefiltert sind (oder umgekehrt). Beide Seiten prüfen denselben Katalog
tests/fixtures/event_filter_parity.json (Frontend: event-filter-parity.test.ts)."""
from __future__ import annotations

import json
import uuid
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.event_filter import event_matches_filter, normalize_event_filter, sort_and_limit

CORPUS = json.loads((Path(__file__).parent / "fixtures" / "event_filter_parity.json").read_text(encoding="utf-8"))
PROTOCOL_DATE = date.fromisoformat(CORPUS["protocol_date"])
EVENTS = [
    SimpleNamespace(
        id=row["id"],
        public_id=uuid.UUID(row["uuid"]),
        event_date=date.fromisoformat(row["event_date"]),
        event_end_date=date.fromisoformat(row["event_end_date"]) if row["event_end_date"] else None,
        title=row["title"],
        tag=row["tag"],
        description=row["description"],
    )
    for row in CORPUS["events"]
]


@pytest.mark.parametrize("case", CORPUS["cases"], ids=[case["name"] for case in CORPUS["cases"]])
def test_pdf_event_filter_matches_the_shared_catalog(case):
    event_filter = normalize_event_filter(case["filter"], default_range_mode="all")
    matching = [event for event in EVENTS if event_matches_filter(event, event_filter, protocol_date=PROTOCOL_DATE, column=case["column"])]
    assert [event.id for event in sort_and_limit(matching, event_filter)] == case["expected"]
