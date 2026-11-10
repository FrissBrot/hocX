"""Regression tests for EventService - previously zero coverage. Covers event CRUD validation
(end-date-before-start-date, participant_count clamping), tenant isolation on list_events (the
recurring IDOR-shaped bug class in this codebase, see test_finance_tenant_scoping.py /
test_fines_tenant_scoping.py for the same pattern elsewhere), and the CSV import path (column
alias resolution, multiple date formats, and that a single bad row aborts the whole import
rather than partially committing)."""
from __future__ import annotations

from datetime import date

import pytest

from app.models.entities import EventCycle
from app.schemas.event import CycleAssignment, EventCreate, EventUpdate
from app.services.event_service import EventService
from tests.factories import make_cycle_config, make_event, make_protocol, make_template, make_tenant


# --- create_event / update_event validation -------------------------------------------------


def test_create_event_basic(db):
    tenant = make_tenant(db, "Event Verein")
    service = EventService()

    event = service.create_event(
        db,
        EventCreate(event_date="2026-03-01", title="Vereinsversammlung", participant_count=12),
        tenant_id=tenant.id,
    )

    assert event.id is not None
    assert event.title == "Vereinsversammlung"
    assert event.participant_count == 12
    assert event.tenant_id == tenant.id


def _cycle_keys(db, event_id):
    return {(row.cycle_config_id, row.cycle_year) for row in db.query(EventCycle).filter(EventCycle.event_id == event_id)}


def test_create_event_assigns_cycle_by_event_date_by_default(db):
    tenant = make_tenant(db, "Zyklus Verein")
    cycle = make_cycle_config(db, tenant.id, reset_month=7, reset_day=31)
    service = EventService()

    july = service.create_event(db, EventCreate(event_date="2026-07-06", title="Sola"), tenant_id=tenant.id)
    august = service.create_event(db, EventCreate(event_date="2026-08-15", title="Arbeitsweekend"), tenant_id=tenant.id)

    assert _cycle_keys(db, july.id) == {(cycle.id, 2025)}
    assert _cycle_keys(db, august.id) == {(cycle.id, 2026)}


def test_create_event_keeps_explicit_cycle_assignments(db):
    tenant = make_tenant(db, "Manuell Verein")
    cycle = make_cycle_config(db, tenant.id, reset_month=7, reset_day=31)
    service = EventService()

    event = service.create_event(
        db,
        EventCreate(event_date="2026-07-06", title="Sola", cycle_assignments=[CycleAssignment(cycle_config_id=cycle.public_id, cycle_year=2026)]),
        tenant_id=tenant.id,
    )
    empty = service.create_event(db, EventCreate(event_date="2026-07-06", title="Ohne", cycle_assignments=[]), tenant_id=tenant.id)

    assert _cycle_keys(db, event.id) == {(cycle.id, 2026)}
    assert _cycle_keys(db, empty.id) == set()


def test_update_event_date_moves_default_cycle_but_keeps_manual_one(db):
    tenant = make_tenant(db, "Verschieben Verein")
    cycle = make_cycle_config(db, tenant.id, reset_month=7, reset_day=31)
    service = EventService()
    default = service.create_event(db, EventCreate(event_date="2026-07-06", title="Auto"), tenant_id=tenant.id)
    manual = service.create_event(
        db,
        EventCreate(event_date="2026-07-06", title="Manuell", cycle_assignments=[CycleAssignment(cycle_config_id=cycle.public_id, cycle_year=2026)]),
        tenant_id=tenant.id,
    )

    service.update_event(db, default.id, EventUpdate(event_date="2026-08-20"))
    service.update_event(db, manual.id, EventUpdate(event_date="2026-06-01"))

    assert _cycle_keys(db, default.id) == {(cycle.id, 2026)}
    assert _cycle_keys(db, manual.id) == {(cycle.id, 2026)}


def test_create_event_end_before_start_raises(db):
    tenant = make_tenant(db, "Invalid Range Verein")
    service = EventService()

    with pytest.raises(ValueError, match="end date must be on or after"):
        service.create_event(
            db,
            EventCreate(event_date="2026-03-10", event_end_date="2026-03-01", title="Zeitreise"),
            tenant_id=tenant.id,
        )


def test_update_event_end_before_start_raises(db):
    tenant = make_tenant(db, "Update Invalid Range Verein")
    event = make_event(db, tenant.id, event_date=date(2026, 3, 1))
    service = EventService()

    with pytest.raises(ValueError, match="end date must be on or after"):
        service.update_event(db, event.id, EventUpdate(event_end_date="2026-02-01"))


def test_update_event_participant_count_clamped_to_zero(db):
    tenant = make_tenant(db, "Clamp Verein")
    event = make_event(db, tenant.id)
    service = EventService()

    updated = service.update_event(db, event.id, EventUpdate(participant_count=-5))

    assert updated.participant_count == 0


def test_update_event_returns_none_for_unknown_id(db):
    service = EventService()
    assert service.update_event(db, 999_999_999, EventUpdate(title="x")) is None


def test_delete_event_returns_false_for_unknown_id(db):
    service = EventService()
    assert service.delete_event(db, 999_999_999) is False


# --- tenant isolation ------------------------------------------------------------------------


def test_list_events_is_scoped_to_tenant(db):
    tenant_a = make_tenant(db, "Tenant A Events")
    tenant_b = make_tenant(db, "Tenant B Events")
    make_event(db, tenant_a.id, title="A-Event")
    make_event(db, tenant_b.id, title="B-Event")

    service = EventService()
    events_a = service.list_events(db, tenant_id=tenant_a.id)

    assert all(e.tenant_id == tenant_a.id for e in events_a)
    assert not any(e.title == "B-Event" for e in events_a)


# --- CSV import -----------------------------------------------------------------------------


def test_import_csv_happy_path_creates_events(db):
    tenant = make_tenant(db, "CSV Import Verein")
    service = EventService()
    csv_text = (
        "Datum,Titel,Teilnehmer\n"
        "01.03.2026,Vorstandssitzung,8\n"
        "2026-04-15,Sommerfest,40\n"
    )

    created = service.import_csv(db, csv_text, tenant_id=tenant.id)

    assert len(created) == 2
    titles = {e.title for e in created}
    assert titles == {"Vorstandssitzung", "Sommerfest"}
    dates = {e.event_date.isoformat() for e in created}
    assert dates == {"2026-03-01", "2026-04-15"}


def test_import_csv_raises_on_invalid_row_and_creates_nothing(db):
    tenant = make_tenant(db, "CSV Error Verein")
    service = EventService()
    csv_text = "Datum,Titel\n01.03.2026,Gueltige Zeile\nnot-a-date,Kaputte Zeile\n"

    with pytest.raises(ValueError):
        service.import_csv(db, csv_text, tenant_id=tenant.id)

    events_after = service.list_events(db, tenant_id=tenant.id)
    assert events_after == []


def test_preview_csv_reports_error_count_without_creating_events(db):
    tenant = make_tenant(db, "CSV Preview Verein")
    service = EventService()
    csv_text = "Datum,Titel\n01.03.2026,Gueltige Zeile\nnot-a-date,Kaputte Zeile\n"

    preview = service.preview_csv(db, csv_text)

    assert preview["valid_count"] == 1
    assert preview["error_count"] == 1
    assert service.list_events(db, tenant_id=tenant.id) == []


def test_preview_csv_empty_input_returns_empty_result(db):
    service = EventService()
    preview = service.preview_csv(db, "")
    assert preview == {"detected_columns": [], "resolved_map": {}, "rows": [], "valid_count": 0, "error_count": 0}


# --- list_for_protocol_cycle: Zyklus-Filter automatischer Matrix-Spalten --------------------


def _event_in_cycle(db, tenant_id, cycle, cycle_year, title):
    event = make_event(db, tenant_id, title=title)
    db.add(EventCycle(event_id=event.id, cycle_config_id=cycle.id, cycle_year=cycle_year))
    db.flush()
    return event


def test_list_for_protocol_cycle_filters_by_chosen_cycle_and_offset(db):
    tenant = make_tenant(db, "Matrix Zyklus Verein")
    vereinsjahr = make_cycle_config(db, tenant.id, name="Vereinsjahr", reset_month=7, reset_day=31)
    semester = make_cycle_config(db, tenant.id, name="Semester", reset_month=1, reset_day=31)
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, protocol_date=date(2026, 10, 12))
    current = _event_in_cycle(db, tenant.id, vereinsjahr, 2026, "Herbstlager")
    previous = _event_in_cycle(db, tenant.id, vereinsjahr, 2025, "Sommerlager")
    _event_in_cycle(db, tenant.id, semester, 2026, "Semesterstart")
    service = EventService()

    items, total, cycle = service.list_for_protocol_cycle(db, protocol=protocol, cycle_config_public_id=vereinsjahr.public_id)
    assert [e.id for e in items] == [current.id]
    assert total == 1
    assert cycle is not None and cycle.cycle_year == 2026

    items, _, cycle = service.list_for_protocol_cycle(
        db, protocol=protocol, cycle_config_public_id=vereinsjahr.public_id, cycle_offset=-1
    )
    assert [e.id for e in items] == [previous.id]
    assert cycle is not None and cycle.cycle_year == 2025


def test_list_for_protocol_cycle_rejects_foreign_cycle(db):
    tenant = make_tenant(db, "Eigener Verein")
    other = make_tenant(db, "Fremder Verein")
    foreign_cycle = make_cycle_config(db, other.id)
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id)

    with pytest.raises(ValueError):
        EventService().list_for_protocol_cycle(db, protocol=protocol, cycle_config_public_id=foreign_cycle.public_id)


def test_event_read_includes_cycle_assignments(db):
    # Regression: PublicIdModel übernahm nur Spalten, cycle_assignments war in jeder
    # Termin-Antwort leer - Zyklus-Filter im Frontend griffen dadurch nie.
    from app.schemas.event import EventRead

    tenant = make_tenant(db, "Read Verein")
    cycle = make_cycle_config(db, tenant.id, reset_month=7, reset_day=31)
    event = EventService().create_event(db, EventCreate(event_date="2026-10-17", title="Herbstlager"), tenant_id=tenant.id)
    db.refresh(event)

    read = EventRead.model_validate(event)
    assert [(a.cycle_config_id, a.cycle_year) for a in read.cycle_assignments] == [(cycle.public_id, 2026)]
