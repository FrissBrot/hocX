"""Termine mit Endzeit, Spezial-Uhrzeiten und Programm (Migration 0184): Speichern über den
Service, Ausgabe im Tabellenblock-PDF (Uhrzeit HH:MM, Termintexte als Markdown) und Endzeit im
Kalender-Abo."""
from __future__ import annotations

from datetime import UTC, date, datetime, time

from app.documents.context import BuildContext
from app.documents.providers.protocol import _event_field_rows
from app.schemas.event import EventCreate, EventRead, EventUpdate
from app.schemas.event_field_config import EVENT_SPECIAL_FIELDS, EventFieldConfig
from app.services import calendar_feed_service
from app.services.event_service import EventService
from tests.factories import make_tenant


def _create(db, tenant_id: int, **values):
    payload = EventCreate(event_date="2026-12-05", title="Chlausabend", **values)
    return EventService().create_event(db, payload, tenant_id=tenant_id)


def test_times_and_program_are_saved_and_read(db):
    tenant = make_tenant(db, "Termin Zeiten")
    event = _create(
        db, tenant.id, start_time="18:30", end_time="21:00", spezial_time1="17:45", program="**Ablauf**\n\n- Chlaus\n- Lebkuchen"
    )
    assert (event.start_time, event.end_time, event.spezial_time1) == (time(18, 30), time(21, 0), time(17, 45))
    assert event.program.startswith("**Ablauf**")

    updated = EventService().update_event(db, event.id, EventUpdate(end_time=None, spezial_time2="22:15"))
    assert updated.end_time is None
    assert updated.spezial_time2 == time(22, 15)
    read = EventRead.model_validate(updated).model_dump(mode="json")
    assert read["start_time"] == "18:30:00"
    assert read["program"].startswith("**Ablauf**")


def test_special_times_are_configurable_like_the_other_special_fields():
    assert {"spezial_time1", "spezial_time2"} <= set(EVENT_SPECIAL_FIELDS)
    config = EventFieldConfig.from_stored({"spezial_time1": {"label": "Treffpunkt", "hidden": False}})
    assert config.spezial_time1.label == "Treffpunkt"
    assert config.spezial_time2.hidden is False


def test_table_block_renders_times_and_markdown_fields(db):
    tenant = make_tenant(db, "Termin PDF")
    event = _create(db, tenant.id, start_time="18:30", program="**Ablauf** mit *Lebkuchen*", location="Pfadiheim")
    ctx = BuildContext(db=db, tenant_id=tenant.id, language="de")
    config = {
        "repeat_source_type": "event",
        "repeat_source_id": str(event.id),
        "event_fields": [
            {"field": "start_time", "label": "", "enabled": True},
            {"field": "program", "label": "", "enabled": True},
            {"field": "location", "label": "Wo", "enabled": True},
            {"field": "end_time", "label": "", "enabled": True},
        ],
    }
    rows = _event_field_rows(ctx, config)
    # Leere Endzeit fällt weg, Reihenfolge wie konfiguriert
    assert [row.label for row in rows] == ["Beginn", "Programm", "Wo"]
    dumped = [row.model_dump() for row in rows]
    assert "18:30" in str(dumped[0]) and "18:30:00" not in str(dumped[0])
    # Markdown wird ausgewertet: fett/kursiv als Auszeichnung statt Sternchen im Text
    assert "**" not in str(dumped[1]) and "Ablauf" in str(dumped[1])


def test_table_block_keeps_saved_field_order_and_skips_disabled_fields(db):
    # Terminfelder sind im Editor sortierbar: das PDF folgt der gespeicherten Reihenfolge, auch
    # wenn sie von der Standardreihenfolge abweicht; abgewählte Felder erscheinen nicht.
    tenant = make_tenant(db, "Termin Reihenfolge")
    event = _create(db, tenant.id, start_time="18:30", location="Pfadiheim")
    ctx = BuildContext(db=db, tenant_id=tenant.id, language="de")
    config = {
        "repeat_source_type": "event",
        "repeat_source_id": str(event.id),
        "event_fields": [
            {"field": "location", "label": "Wo", "enabled": True},
            {"field": "start_time", "label": "", "enabled": True},
            {"field": "title", "label": "", "enabled": False},
        ],
    }
    assert [row.label for row in _event_field_rows(ctx, config)] == ["Wo", "Beginn"]


def test_calendar_entry_uses_end_time_on_the_same_day():
    entry = calendar_feed_service._Entry(
        uid="event-x@hocx",
        start=date(2026, 7, 6),
        end_inclusive=date(2026, 7, 6),
        summary="Sitzung",
        updated_at=datetime(2026, 7, 1, tzinfo=UTC),
        start_time=time(19, 30),
        end_time=time(22, 0),
    )
    ics = calendar_feed_service._render_calendar("Test", [entry])
    assert "DTSTART:20260706T173000Z" in ics
    assert "DTEND:20260706T200000Z" in ics


def test_calendar_entry_ignores_end_time_before_start():
    entry = calendar_feed_service._Entry(
        uid="event-y@hocx",
        start=date(2026, 7, 6),
        end_inclusive=date(2026, 7, 6),
        summary="Sitzung",
        updated_at=datetime(2026, 7, 1, tzinfo=UTC),
        start_time=time(19, 30),
        end_time=time(8, 0),
    )
    ics = calendar_feed_service._render_calendar("Test", [entry])
    assert "DTEND:20260706T183000Z" in ics
