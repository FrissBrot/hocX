"""Teilnehmerzahl über dem int4-Bereich (Bug-Bounty 2026-11-20, termine/fehlerbehandlung).

event.participant_count ist INTEGER (max. 2 147 483 647), Schema und CSV-Import nahmen jede
Python-Zahl an. 3 000 000 000 scheiterte erst beim INSERT/UPDATE (NumericValueOutOfRange):
Anlegen/Ändern 400 mit Eintrag in system_error_log, der CSV-Import brach die ganze Datei mit
«CSV import failed» ab, obwohl die Vorschau die Zeile als gültig gezeigt hatte."""
from __future__ import annotations

from datetime import date

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.api.routes import events as events_routes
from app.schemas.event import EventCreate, EventUpdate
from app.services.event_service import EventService
from tests.factories import make_current_user, make_tenant

TOO_MANY = 3_000_000_000


def test_schema_rejects_participant_count_beyond_integer_column():
    with pytest.raises(ValidationError):
        EventCreate(event_date=date(2026, 5, 1), title="Lager", participant_count=TOO_MANY)
    with pytest.raises(ValidationError):
        EventUpdate(participant_count=TOO_MANY)
    assert EventCreate(event_date=date(2026, 5, 1), title="Lager", participant_count=2_147_483_647).participant_count


def test_create_with_huge_count_is_not_a_database_error(db):
    tenant = make_tenant(db)
    user = make_current_user(tenant.id, role="writer")
    try:
        payload = EventCreate(event_date=date(2026, 5, 1), title="Lager", participant_count=TOO_MANY)
    except ValidationError:
        return  # 422 aus dem Schema - erwartet
    with pytest.raises(HTTPException) as caught:
        events_routes.create_event(payload, db=db, user=user)
    assert not isinstance(caught.value.__cause__, SQLAlchemyError)


def test_csv_preview_flags_huge_participant_count(db):
    csv_text = f"Datum;Titel;Teilnehmer\n01.05.2026;Lager;{TOO_MANY}\n02.05.2026;Hock;12\n"

    rows = EventService().preview_csv(db, csv_text)["rows"]

    assert [row["error_code"] for row in rows] == ["participantCountTooLarge", None]
    assert rows[0]["error_params"] == {"row": 2, "max": 2_147_483_647}
