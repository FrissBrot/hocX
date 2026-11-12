"""Bereichs-Audit Termine und Zyklen (2026-11): Zyklus-Zuordnung beim CSV-Import und bei neuen
bzw. geänderten Zyklus-Definitionen, Löschfolgen, rename-tag (Mandantentrennung, strip, Audit,
Abgabe-Filter), null-Ablehnung im PATCH, übersetzbare CSV-Fehler, Kalender-Abo mit Uhrzeit."""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import text

from app.api.routes import cycle_configs as cycle_routes
from app.api.routes import events as events_routes
from app.models.entities import EventCycle, StoredFile, SubmissionAssignment, SubmissionUpload, SubmissionUploadFile
from app.schemas.cycle_config import CycleConfigCreate, CycleConfigUpdate
from app.schemas.event import EventUpdate
from app.services import calendar_feed_service
from app.services.event_service import EventService
from tests.factories import make_current_user, make_cycle_config, make_event, make_tenant


def _cycle_keys(db, event_id):
    return {(row.cycle_config_id, row.cycle_year) for row in db.query(EventCycle).filter(EventCycle.event_id == event_id)}


# --- Zyklus-Zuordnung ------------------------------------------------------------------------


def test_import_csv_assigns_default_cycles(db):
    tenant = make_tenant(db, "Import Zyklus")
    cycle = make_cycle_config(db, tenant.id, reset_month=7, reset_day=31)
    csv_text = "Startdatum;Titel\n2026-07-06;Sola\n2026-08-15;Arbeitsweekend\n"

    created = EventService().import_csv(db, csv_text, tenant_id=tenant.id)

    by_title = {event.title: event for event in created}
    assert _cycle_keys(db, by_title["Sola"].id) == {(cycle.id, 2025)}
    assert _cycle_keys(db, by_title["Arbeitsweekend"].id) == {(cycle.id, 2026)}


def test_new_cycle_config_applies_to_existing_events(db):
    tenant = make_tenant(db, "Neuer Zyklus")
    user = make_current_user(tenant.id, role="admin")
    event = make_event(db, tenant.id, title="Sola", event_date=date(2026, 7, 6))
    marker = make_event(db, tenant.id, title="Platzhalter", event_date=date(2026, 7, 6))
    marker.is_session_marker = True
    db.flush()

    created = cycle_routes.create_cycle_config(
        CycleConfigCreate(name="Scharjahr", reset_month=7, reset_day=31), db=db, user=user
    )
    cycle_id = db.execute(text("SELECT id FROM cycle_config WHERE public_id = :p"), {"p": created.public_id}).scalar()

    assert _cycle_keys(db, event.id) == {(cycle_id, 2025)}
    assert _cycle_keys(db, marker.id) == set()


def test_changed_reset_date_moves_default_assignments_but_keeps_manual_ones(db):
    tenant = make_tenant(db, "Stichtag")
    user = make_current_user(tenant.id, role="admin")
    cycle = make_cycle_config(db, tenant.id, reset_month=12, reset_day=31)
    autumn = make_event(db, tenant.id, title="Herbstlager", event_date=date(2026, 10, 3))
    manual = make_event(db, tenant.id, title="Manuell", event_date=date(2026, 10, 10))
    db.add(EventCycle(event_id=autumn.id, cycle_config_id=cycle.id, cycle_year=2026))
    db.add(EventCycle(event_id=manual.id, cycle_config_id=cycle.id, cycle_year=2025))
    db.flush()

    cycle_routes.update_cycle_config(cycle.public_id, CycleConfigUpdate(reset_month=7, reset_day=31), db=db, user=user)

    # Standard (31.12. -> 2026) folgt dem neuen Stichtag (31.07. -> Zyklus 2026/27 = 2026) ...
    assert _cycle_keys(db, autumn.id) == {(cycle.id, 2026)}
    # ... ein Termin im Frühling wechselt dagegen tatsächlich den Zyklus:
    spring = make_event(db, tenant.id, title="Frühling", event_date=date(2026, 3, 1))
    db.add(EventCycle(event_id=spring.id, cycle_config_id=cycle.id, cycle_year=2025))  # Standard bei 31.07.
    db.flush()
    cycle_routes.update_cycle_config(cycle.public_id, CycleConfigUpdate(reset_month=12, reset_day=31), db=db, user=user)
    assert _cycle_keys(db, spring.id) == {(cycle.id, 2026)}
    # Manuelle Abweichung bleibt.
    assert _cycle_keys(db, manual.id) == {(cycle.id, 2025)}


# --- Löschen -----------------------------------------------------------------------------------


def _upload_with_file(db, tenant_id, event_id):
    assignment = SubmissionAssignment(
        tenant_id=tenant_id, title="Fotos", public_slug=f"fotos-{uuid.uuid4().hex[:6]}", source_type="events", tag_filter="Lager"
    )
    db.add(assignment)
    db.flush()
    upload = SubmissionUpload(assignment_id=assignment.id, event_id=event_id, status="submitted")
    db.add(upload)
    db.flush()
    stored = StoredFile(tenant_id=tenant_id, original_name="a.jpg", mime_type="image/jpeg", storage_path="abgabebox/a.jpg", file_size_bytes=10)
    db.add(stored)
    db.flush()
    db.add(SubmissionUploadFile(upload_id=upload.id, stored_file_id=stored.id))
    db.flush()


def test_delete_impact_counts_submissions_and_files_and_hides_foreign_events(db):
    tenant = make_tenant(db, "Löschfolgen")
    other = make_tenant(db, "Fremd")
    user = make_current_user(tenant.id, role="writer")
    event = make_event(db, tenant.id, title="Lager", event_date=date(2026, 7, 6))
    foreign = make_event(db, other.id, title="Fremd", event_date=date(2026, 7, 6))
    _upload_with_file(db, tenant.id, event.id)

    impact = events_routes.event_delete_impact(event.public_id, db=db, user=user)
    assert impact == {"submission_count": 1, "file_count": 1}

    with pytest.raises(HTTPException) as exc:
        events_routes.event_delete_impact(foreign.public_id, db=db, user=user)
    assert exc.value.status_code == 404


# --- rename-tag --------------------------------------------------------------------------------


def test_rename_tag_strips_scopes_tenant_moves_assignments_and_audits(db):
    tenant = make_tenant(db, "Umbenennen")
    other = make_tenant(db, "Anderer")
    user = make_current_user(tenant.id, role="writer")
    own = make_event(db, tenant.id, title="A", event_date=date(2026, 5, 1))
    own.tag = "Training"
    foreign = make_event(db, other.id, title="B", event_date=date(2026, 5, 1))
    foreign.tag = "Training"
    assignment = SubmissionAssignment(
        tenant_id=tenant.id, title="Abgabe", public_slug=f"abgabe-{uuid.uuid4().hex[:6]}", source_type="events", tag_filter="Training"
    )
    db.add(assignment)
    db.flush()

    preview = events_routes.rename_tag(
        events_routes.RenameTagPayload(old_tag="Training", new_tag=" Trainings ", dry_run=True), db=db, user=user
    )
    assert preview["events"] == 1 and preview["submission_assignments"] == 1 and preview["updated"] == 0
    db.refresh(own)
    assert own.tag == "Training"

    result = events_routes.rename_tag(
        events_routes.RenameTagPayload(old_tag="Training", new_tag=" Trainings "), db=db, user=user
    )

    assert result["updated"] == 1
    db.refresh(own)
    db.refresh(foreign)
    db.refresh(assignment)
    assert own.tag == "Trainings"
    assert foreign.tag == "Training"
    assert assignment.tag_filter == "Trainings"
    audit_rows = db.execute(
        text("SELECT details_json FROM audit_log WHERE tenant_id = :t AND action = 'event.tag_renamed'"), {"t": tenant.id}
    ).all()
    assert len(audit_rows) == 1
    assert audit_rows[0][0]["new_tag"] == "Trainings"


def test_rename_tag_reports_merge_target(db):
    tenant = make_tenant(db, "Zusammenführen")
    user = make_current_user(tenant.id, role="writer")
    first = make_event(db, tenant.id, title="A", event_date=date(2026, 5, 1))
    first.tag = "Training"
    second = make_event(db, tenant.id, title="B", event_date=date(2026, 5, 2))
    second.tag = "Trainings"
    db.flush()

    preview = events_routes.rename_tag(
        events_routes.RenameTagPayload(old_tag="Training", new_tag="Trainings", dry_run=True), db=db, user=user
    )
    assert preview["target_events"] == 1


def test_rename_tag_rejects_too_long_tag(db):
    tenant = make_tenant(db, "Lang")
    user = make_current_user(tenant.id, role="writer")
    with pytest.raises(HTTPException) as exc:
        events_routes.rename_tag(events_routes.RenameTagPayload(old_tag="A", new_tag="x" * 150), db=db, user=user)
    assert exc.value.status_code == 400


# --- PATCH / CSV-Fehler ------------------------------------------------------------------------


@pytest.mark.parametrize("field", ["event_date", "title", "is_cancelled"])
def test_event_update_rejects_explicit_null(field):
    with pytest.raises(ValidationError):
        EventUpdate.model_validate({field: None})
    # Weglassen bleibt erlaubt.
    assert EventUpdate.model_validate({}).model_dump(exclude_unset=True) == {}


def test_preview_csv_returns_translatable_error_codes(db):
    preview = EventService().preview_csv(db, "Startdatum;Titel;Teilnehmerzahl\n;Ohne Datum;\n31/31/2026;X;\n2026-01-01;Y;viele\n")
    codes = [(row["error_code"], row["error_params"]) for row in preview["rows"]]
    assert codes[0] == ("startDateMissing", {"row": 2})
    assert codes[1][0] == "startDateFormat" and codes[1][1]["row"] == 3
    assert codes[2] == ("participantCountInvalid", {"row": 4})


# --- Kalender-Abo ------------------------------------------------------------------------------


def test_calendar_entry_with_start_time_is_timed_in_utc():
    entry = calendar_feed_service._Entry(
        uid="event-x@hocx",
        start=date(2026, 7, 6),
        end_inclusive=date(2026, 7, 6),
        summary="Sitzung",
        updated_at=datetime(2026, 7, 1, tzinfo=UTC),
        start_time=time(19, 30),
    )
    ics = calendar_feed_service._render_calendar("Test", [entry])
    # 19:30 Sommerzeit (UTC+2) = 17:30 UTC.
    assert "DTSTART:20260706T173000Z" in ics
    assert "DTEND:20260706T183000Z" in ics
    assert "VALUE=DATE" not in ics


def test_calendar_render_uses_swiss_today_for_window(db, monkeypatch):
    captured = {}

    def fake_entries(db, feed, user, *, today):
        captured["today"] = today
        return []

    monkeypatch.setattr(calendar_feed_service, "_event_entries", fake_entries)

    class _Feed:
        kind = "events"
        calendar_name = "Test"

    # 23:30 UTC am 5. Juli = 01:30 am 6. Juli in Zürich.
    calendar_feed_service.render(db, _Feed(), None, now=datetime(2026, 7, 5, 23, 30, tzinfo=UTC))
    assert captured["today"] == date(2026, 7, 6)


def test_cycle_list_uses_swiss_today(db, monkeypatch):
    tenant = make_tenant(db, "Heute")
    user = make_current_user(tenant.id, role="writer")
    cycle = make_cycle_config(db, tenant.id, reset_month=12, reset_day=31)
    monkeypatch.setattr(cycle_routes, "swiss_today", lambda: date(2027, 1, 1))
    years = [c.cycle_year for c in cycle_routes.list_cycles(cycle.public_id, db=db, user=user)]
    assert 2027 in years and 2028 in years


# --- Migration 0178: Nachtrag fehlender Zuordnungen ------------------------------------------


def test_migration_backfills_events_without_any_cycle(db, monkeypatch):
    import importlib.util
    from pathlib import Path

    from app.core.cycle_utils import get_cycle_year

    path = next((Path(__file__).resolve().parents[1] / "alembic/versions").glob("*_event_cycle_backfill.py"))
    spec = importlib.util.spec_from_file_location("migration_event_cycle_backfill", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.op, "execute", lambda sql: db.execute(text(sql)), raising=False)

    tenant = make_tenant(db, "Nachtrag")
    july = make_cycle_config(db, tenant.id, name="Scharjahr", reset_month=7, reset_day=31)
    february = make_cycle_config(db, tenant.id, name="Februar", reset_month=2, reset_day=30)
    dates = [date(2026, 7, 31), date(2026, 8, 1), date(2026, 2, 28), date(2026, 3, 1), date(2026, 12, 31)]
    events = [make_event(db, tenant.id, title=f"E{i}", event_date=d) for i, d in enumerate(dates)]
    manual = make_event(db, tenant.id, title="Manuell", event_date=date(2026, 8, 1))
    db.add(EventCycle(event_id=manual.id, cycle_config_id=july.id, cycle_year=2020))
    db.flush()

    module.upgrade()

    for event in events:
        assert _cycle_keys(db, event.id) == {
            (july.id, get_cycle_year(event.event_date, 7, 31)),
            (february.id, get_cycle_year(event.event_date, 2, 30)),
        }
    assert _cycle_keys(db, manual.id) == {(july.id, 2020)}
