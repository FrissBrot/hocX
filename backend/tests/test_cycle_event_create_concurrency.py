"""Nebenläufigkeit: Zyklus anlegen/ändern gleichzeitig mit Termin anlegen (Nachtlauf 2026-11-19).

`create_cycle_config` las die Termine, `create_event` die Zyklen - beide ohne Sperre. Ein Termin,
der parallel zu einem neuen Zyklus angelegt wurde, sah den (noch nicht committeten) Zyklus nicht,
und der Zyklus sah den (noch nicht committeten) Termin nicht: der Termin bekam für den neuen Zyklus
keine Standard-Zuordnung und fehlte danach in allen Zyklusfiltern (Protokolle, Abgaben, Alben).
Erwartet: Termin-Anlage und Zyklus-Änderung desselben Mandanten laufen nacheinander.
"""

from __future__ import annotations

import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.api.routes import cycle_configs as cycle_routes
from app.core.cycle_utils import get_cycle_year
from app.core.db import engine
from app.models import Event, Tenant
from app.models.entities import CycleConfig, EventCycle
from app.schemas.cycle_config import CycleConfigCreate, CycleConfigUpdate
from app.schemas.event import EventCreate
from app.services.event_service import EventService
from tests.factories import make_current_user, make_cycle_config, make_tenant


def _wait_until_blocked(timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    with engine.connect() as probe:
        while time.monotonic() < deadline:
            if probe.scalar(text("SELECT count(*) FROM pg_locks WHERE NOT granted")):
                return True
            time.sleep(0.05)
    return False


@pytest.fixture
def tenant_id():
    with Session(engine) as setup:
        tenant = make_tenant(setup, f"Zyklus parallel {uuid.uuid4().hex[:6]}")
        setup.commit()
        tid = tenant.id
    yield tid
    with Session(engine) as cleanup:
        cleanup.execute(delete(Tenant).where(Tenant.id == tid))
        cleanup.commit()


def _run_against_open_first(first_action, second_action):
    """Erste Aktion schreibt und hält ihre Transaktion offen (Commit wird zum Flush), die zweite
    startet parallel in eigener Session. Die erste wird im `finally` immer abgeschlossen."""
    pool = ThreadPoolExecutor(1)
    first = Session(engine)
    original_commit = first.commit
    try:
        first.commit = first.flush
        first_action(first)
        first.commit = original_commit
        future = pool.submit(second_action)
        blocked = _wait_until_blocked()
        first.commit()
        future.result(timeout=30)
        return blocked
    finally:
        first.commit = original_commit
        first.rollback()
        first.close()
        pool.shutdown(wait=True)


def _create_cycle(db: Session, tid: int, name: str) -> None:
    user = make_current_user(tid, role="admin")
    cycle_routes.create_cycle_config(CycleConfigCreate(name=name, reset_month=7, reset_day=31), db=db, user=user)


EVENT_DATE = date(2026, 3, 14)


def _create_event(db: Session, tid: int, title: str) -> None:
    EventService().create_event(db, EventCreate(title=title, event_date=EVENT_DATE), tenant_id=tid)


def _assignments(tid: int, title: str, cycle_name: str) -> list[int]:
    with Session(engine) as check:
        return list(check.scalars(
            select(EventCycle.cycle_year)
            .join(Event, Event.id == EventCycle.event_id)
            .join(CycleConfig, CycleConfig.id == EventCycle.cycle_config_id)
            .where(Event.tenant_id == tid, Event.title == title, CycleConfig.name == cycle_name)
        ))


def test_event_created_while_a_cycle_is_created_gets_its_default_assignment(tenant_id):
    def second():
        with Session(engine) as db:
            _create_cycle(db, tenant_id, "Vereinsjahr")

    blocked = _run_against_open_first(lambda first: _create_event(first, tenant_id, "Hock"), second)
    assert _assignments(tenant_id, "Hock", "Vereinsjahr") == [get_cycle_year(EVENT_DATE, 7, 31)], "Termin fehlt im neuen Zyklus"
    assert blocked, "Zyklus-Anlage wartet nicht auf die laufende Termin-Anlage"


def test_cycle_created_while_an_event_is_created_assigns_the_event(tenant_id):
    def second():
        with Session(engine) as db:
            _create_event(db, tenant_id, "Hock")

    blocked = _run_against_open_first(lambda first: _create_cycle(first, tenant_id, "Vereinsjahr"), second)
    assert _assignments(tenant_id, "Hock", "Vereinsjahr") == [get_cycle_year(EVENT_DATE, 7, 31)], "Termin fehlt im neuen Zyklus"
    assert blocked, "Termin-Anlage wartet nicht auf die laufende Zyklus-Anlage"


def test_event_created_while_the_cycle_reset_day_moves_follows_the_new_reset(tenant_id):
    with Session(engine) as setup:
        cycle = make_cycle_config(setup, tenant_id, name="Vereinsjahr", reset_month=12, reset_day=31)
        setup.commit()
        cycle_public_id = cycle.public_id

    def first_action(first: Session) -> None:
        user = make_current_user(tenant_id, role="admin")
        # Stichtag 31.12. -> 31.7.: der Termin gehört danach zu einem anderen Zyklusjahr.
        cycle_routes.update_cycle_config(cycle_public_id, CycleConfigUpdate(reset_month=7, reset_day=31), db=first, user=user)

    def second():
        with Session(engine) as db:
            _create_event(db, tenant_id, "Hock")

    assert get_cycle_year(EVENT_DATE, 7, 31) != get_cycle_year(EVENT_DATE, 12, 31)
    blocked = _run_against_open_first(first_action, second)
    assert _assignments(tenant_id, "Hock", "Vereinsjahr") == [get_cycle_year(EVENT_DATE, 7, 31)]
    assert blocked, "Termin-Anlage wartet nicht auf die Stichtag-Änderung"
