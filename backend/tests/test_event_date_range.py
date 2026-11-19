"""Termindaten ausserhalb eines plausiblen Bereichs (Bug-Bounty 2026-11-19, termine/eingaben).

Ohne Grenze nahmen POST/PATCH /events und der CSV-Import jedes ISO-Datum an. Ein Termin mit
Enddatum 9999-12-31 brachte danach das Kalender-Abo des Mandanten zum Absturz (DTEND = +1 Tag),
ein Datum 0001-01-01 die Zyklusberechnung (Jahr 0)."""
from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from app.schemas.event import EVENT_DATE_MAX, EVENT_DATE_MIN, EventCreate, EventUpdate
from app.services.event_service import EventService


@pytest.mark.parametrize("field", ["event_date", "event_end_date"])
@pytest.mark.parametrize("value", [date(9999, 12, 31), date(1, 1, 1)])
def test_create_rejects_dates_outside_the_plausible_range(field, value):
    data = {"event_date": date(2026, 5, 1), "title": "Lager", field: value}
    with pytest.raises(ValidationError):
        EventCreate(**data)


@pytest.mark.parametrize("field", ["event_date", "event_end_date"])
def test_update_rejects_dates_outside_the_plausible_range(field):
    with pytest.raises(ValidationError):
        EventUpdate(**{field: date(9999, 12, 31)})


def test_range_limits_themselves_are_accepted():
    created = EventCreate(event_date=EVENT_DATE_MIN, event_end_date=EVENT_DATE_MAX, title="Grenzen")
    assert created.event_end_date == EVENT_DATE_MAX
    assert EventUpdate(event_end_date=None).event_end_date is None


def test_csv_preview_flags_dates_outside_the_plausible_range(db):
    csv_text = "Datum;Enddatum;Titel\n01.05.2026;31.12.9999;Endlos\n0001-01-01;;Uralt\n01.05.2026;;Normal\n"

    preview = EventService().preview_csv(db, csv_text)

    rows = preview["rows"]
    assert [row["error_code"] for row in rows] == ["dateOutOfRange", "dateOutOfRange", None]
    assert rows[0]["error_params"] == {"row": 2, "value": "31.12.9999"}
    assert preview["valid_count"] == 1
