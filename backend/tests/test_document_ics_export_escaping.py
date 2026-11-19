"""ICS-Export des Document Studio: Steuerzeichen in Termintexten (Bug-Bounty 2026-11-19,
termine/eingaben).

`documents/providers/events.py::ics` escapte nur `\\n`. Ein Wagenrücklauf im Titel blieb roh
stehen; Kalender-Parser, die auch einzelne CR als Zeilenende lesen, übernahmen dahinter
eingeschleuste Eigenschaften oder ganze Termine. Das Kalender-Abo (calendar_feed_service) war
schon richtig, der Export muss dieselbe Escaping-Regel nutzen."""
from __future__ import annotations

from datetime import date

from app.documents.providers import events as event_provider
from tests.factories import make_event, make_tenant


def _content_lines(ics: str) -> list[str]:
    # Entfaltete Inhaltszeilen nach RFC 5545 (CRLF + Leerzeichen = Fortsetzung)
    return ics.replace("\r\n ", "").split("\r\n")


def test_carriage_return_in_event_texts_cannot_start_a_new_ics_line(db):
    tenant = make_tenant(db)
    event = make_event(
        db, tenant.id,
        title="Hock\rEND:VEVENT\rBEGIN:VEVENT\rSUMMARY:Gratis-Bier\rURL:https://example.invalid/x",
        event_date=date(2026, 6, 1),
    )
    event.description = "Zeile 1\r\nZeile 2\x0bvertikal"
    event.location = "Saal\rATTACH:https://example.invalid/a"
    db.flush()

    ics = event_provider.ics([event], tenant_name="Verein\rX-INJECT:1")

    # Keine Steuerzeichen ausser dem CRLF-Zeilenende
    for line in _content_lines(ics):
        assert not any(ord(ch) < 0x20 for ch in line), repr(line)
    lines = _content_lines(ics)
    assert lines.count("BEGIN:VEVENT") == 1
    assert not any(line.startswith(("URL:", "ATTACH:", "X-INJECT:")) for line in lines)
    assert "DESCRIPTION:Zeile 1\\nZeile 2vertikal" in lines


def test_long_event_texts_are_folded_to_75_octets(db):
    tenant = make_tenant(db)
    event = make_event(db, tenant.id, title="Sommerlager " * 20, event_date=date(2026, 7, 1))
    db.flush()

    ics = event_provider.ics([event], tenant_name="Verein")

    assert all(len(raw.encode()) <= 75 for raw in ics.split("\r\n"))
