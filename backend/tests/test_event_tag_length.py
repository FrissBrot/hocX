"""Tag-Länge bei Terminen (Bug-Bounty 2026-11-19, termine/eingaben).

rename-tag begrenzt den neuen Tag auf MAX_TAG_LENGTH (100) und den alten auf 200 Zeichen,
Anlegen, Ändern und der CSV-Import aber gar nicht. Ein so entstandener langer Tag liess sich
danach nie mehr umbenennen oder zusammenführen (422 auf old_tag)."""
from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from app.api.routes import events as events_routes
from app.schemas.event import EVENT_TAG_MAX_LENGTH, EventCreate, EventUpdate
from app.services.event_service import EventService
from tests.factories import make_current_user, make_event, make_tenant


def test_create_and_update_reject_tags_longer_than_the_rename_limit():
    too_long = "x" * (EVENT_TAG_MAX_LENGTH + 1)
    with pytest.raises(ValidationError):
        EventCreate(event_date=date(2026, 5, 1), title="Lager", tag=too_long)
    with pytest.raises(ValidationError):
        EventUpdate(tag=too_long)
    assert EventCreate(event_date=date(2026, 5, 1), title="Lager", tag="x" * EVENT_TAG_MAX_LENGTH).tag


def test_csv_preview_flags_too_long_tags(db):
    csv_text = f"Datum;Titel;Tag\n01.05.2026;Lager;{'t' * 300}\n02.05.2026;Hock;Hock\n"

    rows = EventService().preview_csv(db, csv_text)["rows"]

    assert [row["error_code"] for row in rows] == ["tagTooLong", None]
    assert rows[0]["error_params"] == {"row": 2, "max": EVENT_TAG_MAX_LENGTH}


def test_existing_overlong_tag_can_still_be_renamed(db):
    tenant = make_tenant(db)
    user = make_current_user(tenant.id, role="writer")
    legacy = "Altlast " * 40  # 320 Zeichen, vor der Begrenzung entstanden
    event = make_event(db, tenant.id, title="Alt", event_date=date(2026, 5, 1))
    event.tag = legacy
    db.flush()

    result = events_routes.rename_tag(events_routes.RenameTagPayload(old_tag=legacy, new_tag="Altlast"), db=db, user=user)

    assert result["updated"] == 1
    db.refresh(event)
    assert event.tag == "Altlast"
