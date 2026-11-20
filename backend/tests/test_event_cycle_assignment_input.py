"""Zyklus-Zuordnungen eines Termins aus der API (Bug-Bounty 2026-11-20, termine/fehlerbehandlung).

event_cycle.cycle_year ist SMALLINT und Teil des Primärschlüssels (event_id, cycle_config_id,
cycle_year). Ein cycle_year ausserhalb davon (z. B. 40000) oder derselbe Zyklus zweimal in
cycle_assignments scheiterten erst beim INSERT (DataError/IntegrityError): Anlegen bzw. Ändern
antwortete mit 400 und schrieb jedes Mal einen Eintrag ins Fehlerprotokoll."""
from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.api.routes import events as events_routes
from app.models.entities import EventCycle
from app.schemas.event import CycleAssignment, EventCreate, EventUpdate
from tests.factories import make_current_user, make_cycle_config, make_event, make_tenant


def test_cycle_year_outside_smallint_is_rejected_by_the_schema():
    cfg_id = "00000000-0000-0000-0000-000000000001"
    with pytest.raises(ValidationError):
        CycleAssignment(cycle_config_id=cfg_id, cycle_year=40000)
    assert CycleAssignment(cycle_config_id=cfg_id, cycle_year=2026).cycle_year == 2026


def _cycle_rows(db, event_id: int) -> list[tuple[int, int]]:
    return [(row.cycle_config_id, row.cycle_year) for row in db.scalars(select(EventCycle).where(EventCycle.event_id == event_id))]


def test_duplicate_cycle_assignment_on_update_is_stored_once(db):
    tenant = make_tenant(db)
    user = make_current_user(tenant.id, role="writer")
    cfg = make_cycle_config(db, tenant.id)
    event = make_event(db, tenant.id, title="Hock", event_date=date(2026, 5, 1))
    db.commit()
    assignment = {"cycle_config_id": str(cfg.public_id), "cycle_year": 2026}

    events_routes.patch_event(
        event.public_id, EventUpdate.model_validate({"cycle_assignments": [assignment, assignment]}), db=db, user=user
    )

    assert _cycle_rows(db, event.id) == [(cfg.id, 2026)]


def test_duplicate_cycle_assignment_on_create_is_stored_once(db):
    tenant = make_tenant(db)
    user = make_current_user(tenant.id, role="writer")
    cfg = make_cycle_config(db, tenant.id)
    db.commit()
    assignment = {"cycle_config_id": str(cfg.public_id), "cycle_year": 2026}

    created = events_routes.create_event(
        EventCreate.model_validate({"event_date": "2026-05-01", "title": "Hock", "cycle_assignments": [assignment, assignment]}),
        db=db,
        user=user,
    )

    assert _cycle_rows(db, created.id) == [(cfg.id, 2026)]
