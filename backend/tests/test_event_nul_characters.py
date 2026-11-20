"""NUL-Zeichen in Termin-Eingaben (Bug-Bounty 2026-11-20, termine/fehlerbehandlung).

PostgreSQL-Text und JSONB können kein U+0000 speichern. Ohne Prüfung scheiterte erst das SQL mit
psycopg.DataError: «Tag umbenennen», Kalender-Abo und Feldbezeichnungen antworteten mit 500,
Anlegen/Ändern von Terminen und Zyklen sowie der CSV-Import mit 400 - aber jeweils mit einem
Eintrag in system_error_log, als wäre es ein unerwarteter Serverfehler."""
from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from app.api.routes import events as events_routes
from app.schemas.calendar_feed import CalendarFeedUpsert
from app.schemas.cycle_config import CycleConfigCreate, CycleConfigUpdate
from app.schemas.event import EventCreate, EventUpdate
from app.schemas.event_field_config import EventFieldSetting
from app.services.event_service import EventService
from tests.factories import make_tenant


def test_rename_tag_rejects_nul_instead_of_database_error():
    with pytest.raises(ValidationError):
        events_routes.RenameTagPayload(old_tag="Hock\x00", new_tag="Neu")
    with pytest.raises(ValidationError):
        events_routes.RenameTagPayload(old_tag="Hock", new_tag="N\x00eu")


@pytest.mark.parametrize("field", ["title", "tag", "description", "location", "spezial_text1", "program"])
def test_event_create_and_update_reject_nul(field):
    with pytest.raises(ValidationError):
        EventCreate(event_date=date(2026, 5, 1), **{"title": "Hock", field: "a\x00b"})
    with pytest.raises(ValidationError):
        EventUpdate(**{field: "a\x00b"})


def test_event_create_still_accepts_normal_text():
    created = EventCreate(event_date=date(2026, 5, 1), title="Hock ✓", description="Zeile 1\nZeile 2")
    assert created.description == "Zeile 1\nZeile 2"


def test_cycle_config_calendar_feed_and_field_label_reject_nul():
    with pytest.raises(ValidationError):
        CycleConfigCreate(name="Jahr\x00")
    with pytest.raises(ValidationError):
        CycleConfigUpdate(name_pattern="{year}\x00")
    with pytest.raises(ValidationError):
        CalendarFeedUpsert(calendar_name="hocX\x00")
    with pytest.raises(ValidationError):
        EventFieldSetting(label="Ort\x00")


def test_csv_with_nul_is_an_input_error_in_preview_and_import(db):
    tenant = make_tenant(db)
    csv_text = "Datum;Titel\n01.05.2026;Ho\x00ck\n"

    with pytest.raises(ValueError, match="NUL"):
        EventService().preview_csv(db, csv_text)
    with pytest.raises(ValueError, match="NUL"):
        EventService().import_csv(db, csv_text, tenant_id=tenant.id)
