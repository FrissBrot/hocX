"""Nebenläufigkeit beim Bearbeiten eines Termins.

update_event las den Termin ohne Sperre und ersetzte die Zyklus-Zuordnungen per DELETE + INSERT.
- Zwei gleichzeitige PATCH mit Zyklus-Zuordnungen (zwei Personen haken denselben Zyklus an): der
  zweite löschte nichts mehr (schon gelöscht), fügte dieselbe Zeile erneut ein und scheiterte an
  pk_event_cycle → 400 «Event could not be updated» und Eintrag im Fehlerprotokoll.
- PATCH, während der Termin gelöscht wird: UPDATE auf eine verschwundene Zeile (StaleDataError)
  → 400 und Fehlerprotokoll statt 404.
Erwartet: der zweite Request wartet auf den ersten und arbeitet auf dessen Stand.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, text
from sqlalchemy.orm import Session

from app.api.routes import events as events_routes
from app.core.db import engine
from app.models import Event, Tenant
from app.models.entities import EventCycle, SystemErrorLog
from app.schemas.event import CycleAssignment, EventUpdate
from app.services.event_service import EventService
from tests.factories import make_current_user, make_cycle_config, make_event, make_tenant


def _wait_until_blocked(timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    with engine.connect() as probe:
        while time.monotonic() < deadline:
            waiting = probe.scalar(text("SELECT count(*) FROM pg_locks WHERE NOT granted"))
            if waiting:
                return True
            time.sleep(0.05)
    return False


@pytest.fixture
def committed_event():
    with Session(engine) as setup:
        tenant = make_tenant(setup, "Termin parallel")
        cycle = make_cycle_config(setup, tenant.id, name="Vereinsjahr", reset_month=12, reset_day=31)
        event = make_event(setup, tenant.id, title="GV", event_date=date(2026, 3, 14))
        setup.commit()
        data = {"tenant_id": tenant.id, "event_id": event.id, "event_public_id": event.public_id, "cycle_public_id": cycle.public_id}
    yield data
    with Session(engine) as cleanup:
        cleanup.execute(delete(SystemErrorLog).where(SystemErrorLog.tenant_id == data["tenant_id"]))
        cleanup.execute(delete(Tenant).where(Tenant.id == data["tenant_id"]))
        cleanup.commit()


def _hold_first(first: Session, action) -> None:
    """Erster Request: Änderung geschrieben, Commit noch nicht durch (wie mitten in der Route)."""
    original_commit = first.commit
    first.commit = first.flush
    try:
        action()
    finally:
        first.commit = original_commit


def _second_patch(data, payload: EventUpdate):
    user = make_current_user(data["tenant_id"])
    with Session(engine) as db:
        try:
            events_routes.patch_event(data["event_public_id"], payload, db=db, user=user)
        except HTTPException as exc:
            return exc.status_code
    return 200


def _run_against_open_first(data, first_action, second_payload: EventUpdate) -> tuple[int, bool]:
    """Erster Request schreibt und hält seine Transaktion offen, der zweite startet parallel.
    Der erste wird in jedem Fall abgeschlossen, damit der zweite nie endlos wartet."""
    pool = ThreadPoolExecutor(1)
    first = Session(engine)
    try:
        _hold_first(first, lambda: first_action(first))
        future = pool.submit(_second_patch, data, second_payload)
        blocked = _wait_until_blocked()
        first.commit()
        return future.result(timeout=30), blocked
    finally:
        first.rollback()
        first.close()
        pool.shutdown(wait=True)


def test_parallel_cycle_assignment_patches_do_not_collide(committed_event):
    data = committed_event
    payload = EventUpdate(cycle_assignments=[CycleAssignment(cycle_config_id=data["cycle_public_id"], cycle_year=2025)])
    status, blocked = _run_against_open_first(
        data, lambda first: EventService().update_event(first, data["event_id"], payload), payload
    )
    assert blocked, "zweiter PATCH wartet nicht auf den ersten"

    with Session(engine) as check:
        years = [row.cycle_year for row in check.query(EventCycle).filter(EventCycle.event_id == data["event_id"])]
        errors = check.query(SystemErrorLog).filter(SystemErrorLog.tenant_id == data["tenant_id"]).count()
    assert status == 200, f"zweiter gleichzeitiger PATCH: {status}"
    assert years == [2025]
    assert errors == 0


def test_patch_while_event_is_deleted_returns_404(committed_event):
    data = committed_event
    status, blocked = _run_against_open_first(
        data, lambda first: first.execute(delete(Event).where(Event.id == data["event_id"])), EventUpdate(title="Neu")
    )
    assert blocked, "PATCH wartet nicht auf das Löschen"

    with Session(engine) as check:
        errors = check.query(SystemErrorLog).filter(SystemErrorLog.tenant_id == data["tenant_id"]).count()
    assert status == 404
    assert errors == 0
