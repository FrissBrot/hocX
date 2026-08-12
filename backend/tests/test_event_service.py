"""Regression tests for EventService - previously zero coverage. Covers event CRUD validation
(end-date-before-start-date, participant_count clamping), tenant isolation on list_events (the
recurring IDOR-shaped bug class in this codebase, see test_finance_tenant_scoping.py /
test_fines_tenant_scoping.py for the same pattern elsewhere), and the CSV import path (column
alias resolution, multiple date formats, and that a single bad row aborts the whole import
rather than partially committing)."""
from __future__ import annotations

from datetime import date

import pytest

from app.schemas.event import EventCreate, EventUpdate
from app.services.event_service import EventService
from tests.factories import make_event, make_tenant


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
