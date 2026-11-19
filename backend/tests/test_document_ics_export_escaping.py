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


def test_unicode_line_separators_cannot_start_a_new_ics_line(db):
    """U+0085/U+2028/U+2029 (und DEL): Parser mit splitlines() (Python icalendar) brechen dort um.
    Kalender-Abo und Export nutzen dasselbe _escape (Review 2026-11-19)."""
    tenant = make_tenant(db)
    title = "Hock\u2028URL:https://example.invalid/a\u2029ATTACH:x\x85X-INJECT:1\x7fEnde"
    event = make_event(db, tenant.id, title=title, event_date=date(2026, 6, 1))
    db.flush()

    ics = event_provider.ics([event], tenant_name="Verein\u2028X-INJECT:2")

    lines = _content_lines(ics)
    assert all(len(line.splitlines()) <= 1 for line in lines), lines
    assert "".join(lines).splitlines() == ["".join(lines)]
    assert "SUMMARY:HockURL:https://example.invalid/aATTACH:xX-INJECT:1Ende" in lines


def test_end_date_at_the_end_of_the_calendar_does_not_overflow(db):
    """Altdaten mit Enddatum 9999-12-31: DTEND (+1 Tag) lief über date.max (wie der Feed-Fix
    aus PR #65)."""
    tenant = make_tenant(db)
    endless = make_event(db, tenant.id, title="Endlos", event_date=date(2026, 6, 1), event_end_date=date(9999, 12, 31))
    last_day = make_event(db, tenant.id, title="Letzter Tag", event_date=date(9999, 12, 31))
    db.flush()

    lines = _content_lines(event_provider.ics([endless, last_day], tenant_name="Verein"))

    assert lines.count("DTEND;VALUE=DATE:99991231") == 2
    assert "SUMMARY:Endlos" in lines and "SUMMARY:Letzter Tag" in lines
