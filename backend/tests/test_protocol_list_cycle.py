"""Zyklus-Gruppierung der Protokoll-Liste (GET /api/protocols -> ProtocolRead.cycle)."""
from __future__ import annotations

import uuid
from datetime import date
from types import SimpleNamespace

from app.api.routes.protocols import _protocol_list_cycle

TODAY = date(2026, 10, 4)


def _cfg(name_pattern: str | None = None):
    return SimpleNamespace(public_id=uuid.UUID(int=1), name="Zyklus", reset_month=7, reset_day=31, name_pattern=name_pattern)


def test_cycle_from_config_without_pattern_uses_config_name():
    cycle = _protocol_list_cycle(date(2026, 8, 12), _cfg(), today=TODAY)
    assert cycle.name == "Zyklus 2026/2027"
    assert (cycle.start_date, cycle.end_date) == (date(2026, 8, 1), date(2027, 7, 31))
    assert cycle.is_current is True


def test_reset_day_still_belongs_to_previous_cycle():
    cycle = _protocol_list_cycle(date(2026, 7, 31), _cfg(), today=TODAY)
    assert cycle.cycle_year == 2025
    assert cycle.name == "Zyklus 2025/2026"
    assert cycle.is_current is False


def test_name_pattern_wins():
    cycle = _protocol_list_cycle(date(2026, 6, 28), _cfg("Scharjahr [cy]/[cy_end]"), today=TODAY)
    assert cycle.name == "Scharjahr 2025/2026"


def test_template_without_cycle_falls_back_to_calendar_year():
    cycle = _protocol_list_cycle(date(2025, 1, 5), None, today=TODAY)
    assert cycle.name is None
    assert cycle.key == "year:2025"
    assert (cycle.start_date, cycle.end_date) == (date(2025, 1, 1), date(2025, 12, 31))
