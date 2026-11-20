"""Terminfilter-Fenster am Kalenderrand (Bug-Bounty 2026-11-20, termine/fehlerbehandlung).

Fenster-Tage kamen per API ungeprüft an (Editor: Stepper); ab ca. 3 Mio. Tagen brach jedes
Rendern des Protokolls/Dokuments mit OverflowError ab. Der Paritätsfall
«fenster_ueber_kalendergrenze» (fixtures/event_filter_parity.json) deckt die Grenze ab; hier
zusätzlich ein Sitzungsdatum am Kalenderrand (Altbestand)."""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from app.services.event_filter import WINDOW_DAYS_LIMIT, event_matches_filter, normalize_event_filter


def test_window_days_are_clamped_on_normalize():
    normalized = normalize_event_filter({"range": {"mode": "window", "start_days": -10**12, "end_days": 10**12}})

    assert normalized["range"]["start_days"] == -WINDOW_DAYS_LIMIT
    assert normalized["range"]["end_days"] == WINDOW_DAYS_LIMIT


def test_window_at_calendar_edge_does_not_overflow():
    event = SimpleNamespace(id=1, event_date=date(1, 1, 3), event_end_date=None, tag="", title="Alt", description="")
    event_filter = normalize_event_filter({"range": {"mode": "window", "start_days": -30, "end_days": 30}})

    assert event_matches_filter(event, event_filter, protocol_date=date(1, 1, 5)) is True
    assert event_matches_filter(event, event_filter, protocol_date=date(9999, 12, 20)) is False
