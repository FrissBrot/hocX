"""Regression tests for the 5 "Mittel" findings from the 2026-08-13 audit pass (Todos/
Zyklen/Teilnehmer-Zuweisungen). Each test is named after the finding it covers (M5/M6/M13/
M14/M15).
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select

from app.api.routes import cycle_configs as cycle_configs_route
from app.core.cycle_utils import get_cycle_year
from app.models.entities import CycleConfig, Participant, TodoStatus
from app.schemas.event import EventCreate, EventUpdate
from app.schemas.protocol import ProtocolTodoUpdate
from app.services.event_service import EventService
from app.services.protocol_service import ProtocolService
from app.services.protocol_todo_service import ProtocolTodoService

from tests.factories import (
    make_current_user,
    make_participant,
    make_protocol,
    make_protocol_element,
    make_protocol_element_block,
    make_protocol_todo,
    make_template,
    make_template_participant,
    make_tenant,
)

protocol_service = ProtocolService()
todo_service = ProtocolTodoService()
event_service = EventService()


# --- M5: get_cycle_year vs. ProtocolService._cycle_bounds must agree -----------------------


def test_m5_get_cycle_year_matches_cycle_bounds_for_default_reset():
    """reset_month=12/reset_day=31 (the CycleConfig default) used to make get_cycle_year
    return d.year - 1 for every date, while _cycle_bounds correctly treated the cycle as the
    plain calendar year (d.year). Both must now agree."""
    for d in (date(2026, 1, 1), date(2026, 6, 15), date(2026, 12, 31)):
        cycle_year = get_cycle_year(d, 12, 31)
        cycle_start, _cycle_end = protocol_service._cycle_bounds(d, reset_month=12, reset_day=31)
        assert cycle_year == cycle_start.year == d.year


def test_m5_get_cycle_year_matches_cycle_bounds_for_non_default_reset():
    """Non-default reset dates (e.g. 31 Jul, matching the function's own docstring example)
    must keep behaving as documented - this is the case the old implementation happened to
    get right, so the fix must not regress it."""
    cases = [date(2025, 8, 1), date(2025, 7, 31), date(2025, 1, 1), date(2025, 12, 31)]
    for d in cases:
        cycle_year = get_cycle_year(d, 7, 31)
        cycle_start, _cycle_end = protocol_service._cycle_bounds(d, reset_month=7, reset_day=31)
        assert cycle_year == cycle_start.year
    assert get_cycle_year(date(2025, 8, 1), 7, 31) == 2025
    assert get_cycle_year(date(2025, 7, 31), 7, 31) == 2024


# --- M6: create_quick_todo must look up the "open" status by code, not hardcode id=1 -------


def test_m6_create_quick_todo_uses_open_status_code(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id)

    _block, todo = protocol_service.create_quick_todo(
        db, protocol_id=protocol.id, task="Neues Todo", tag="Sitzung", created_by=None,
    )

    open_status_id = db.scalar(select(TodoStatus.id).where(TodoStatus.code == "open"))
    assert todo.todo_status_id == open_status_id


# --- M13: current_cycle_year must be included even with no matching protocol yet -----------


def test_m13_list_cycles_includes_current_cycle_year_without_matching_protocol(db):
    tenant = make_tenant(db)
    cfg = CycleConfig(tenant_id=tenant.id, name="Standard", reset_month=12, reset_day=31)
    db.add(cfg)
    db.flush()
    user = make_current_user(tenant.id, role="reader")

    result = cycle_configs_route.list_cycles(cfg.id, db=db, user=user)

    current_cycle_year = get_cycle_year(date.today(), cfg.reset_month, cfg.reset_day)
    years = {c.cycle_year for c in result}
    assert current_cycle_year in years


# --- M14: completed_at must be server-authoritative on status change -----------------------


def _make_todo_block(db, tenant, template):
    protocol = make_protocol(db, tenant.id, template.id)
    element = make_protocol_element(db, protocol.id)
    block = make_protocol_element_block(db, element.id, configuration_snapshot_json={}, element_type_code="todo")
    return block


def test_m14_completed_at_set_on_transition_to_done(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    block = _make_todo_block(db, tenant, template)
    todo = make_protocol_todo(db, block.id)
    assert todo.completed_at is None

    done_status_id = db.scalar(select(TodoStatus.id).where(TodoStatus.code == "done"))
    updated = todo_service.update_todo(db, todo.id, ProtocolTodoUpdate(todo_status_id=done_status_id))

    assert updated.completed_at is not None


def test_m14_completed_at_cleared_on_reopen(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    block = _make_todo_block(db, tenant, template)
    todo = make_protocol_todo(db, block.id)
    done_status_id = db.scalar(select(TodoStatus.id).where(TodoStatus.code == "done"))
    open_status_id = db.scalar(select(TodoStatus.id).where(TodoStatus.code == "open"))
    todo_service.update_todo(db, todo.id, ProtocolTodoUpdate(todo_status_id=done_status_id))

    reopened = todo_service.update_todo(db, todo.id, ProtocolTodoUpdate(todo_status_id=open_status_id))

    assert reopened.completed_at is None


def test_m14_client_supplied_completed_at_is_ignored(db):
    """A client sending todo_status_id=open together with a stale completed_at from an old
    payload must not resurrect a bogus completion timestamp."""
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    block = _make_todo_block(db, tenant, template)
    todo = make_protocol_todo(db, block.id)
    open_status_id = db.scalar(select(TodoStatus.id).where(TodoStatus.code == "open"))
    bogus = datetime(2020, 1, 1, tzinfo=timezone.utc)

    updated = todo_service.update_todo(
        db, todo.id, ProtocolTodoUpdate(todo_status_id=open_status_id, completed_at=bogus),
    )

    assert updated.completed_at is None


# --- M15a: participant_allowed_for_block must respect joined_at/left_at --------------------


def test_m15_participant_allowed_for_block_rejects_departed_participant(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, protocol_date=date(2026, 6, 1))
    element = make_protocol_element(db, protocol.id)
    block = make_protocol_element_block(db, element.id, configuration_snapshot_json={}, element_type_code="todo")
    participant = make_participant(db, tenant.id)
    participant.left_at = date(2026, 1, 1)  # left before the protocol's date
    db.flush()
    make_template_participant(db, template.id, participant.id)

    assert todo_service.repository.participant_allowed_for_block(db, block.id, participant.id) is False


def test_m15_participant_allowed_for_block_accepts_active_participant(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, protocol_date=date(2026, 6, 1))
    element = make_protocol_element(db, protocol.id)
    block = make_protocol_element_block(db, element.id, configuration_snapshot_json={}, element_type_code="todo")
    participant = make_participant(db, tenant.id)
    db.flush()
    make_template_participant(db, template.id, participant.id)

    assert todo_service.repository.participant_allowed_for_block(db, block.id, participant.id) is True


# --- M15b: EventService must validate organizer/leadership/participant/spezial ids ----------


def test_m15_create_event_rejects_foreign_tenant_participant_id(db):
    tenant_a = make_tenant(db, "Tenant A")
    tenant_b = make_tenant(db, "Tenant B")
    foreign_participant = make_participant(db, tenant_b.id)

    with pytest.raises(ValueError):
        event_service.create_event(
            db,
            EventCreate(
                event_date=date(2026, 1, 1),
                title="Test Event",
                organizer_ids=[foreign_participant.id],
            ),
            tenant_id=tenant_a.id,
        )


def test_m15_create_event_rejects_nonexistent_participant_id(db):
    tenant = make_tenant(db)

    with pytest.raises(ValueError):
        event_service.create_event(
            db,
            EventCreate(
                event_date=date(2026, 1, 1),
                title="Test Event",
                participant_ids=[999_999_999],
            ),
            tenant_id=tenant.id,
        )


def test_m15_create_event_accepts_own_tenant_participant_id(db):
    tenant = make_tenant(db)
    participant = make_participant(db, tenant.id)

    event = event_service.create_event(
        db,
        EventCreate(
            event_date=date(2026, 1, 1),
            title="Test Event",
            leadership_ids=[participant.id],
        ),
        tenant_id=tenant.id,
    )

    assert event.leadership_ids == [participant.id]


def test_m15_update_event_rejects_foreign_tenant_participant_id(db):
    tenant_a = make_tenant(db, "Tenant A")
    tenant_b = make_tenant(db, "Tenant B")
    foreign_participant = make_participant(db, tenant_b.id)
    event = event_service.create_event(
        db, EventCreate(event_date=date(2026, 1, 1), title="Test Event"), tenant_id=tenant_a.id,
    )

    with pytest.raises(ValueError):
        event_service.update_event(db, event.id, EventUpdate(spezial1_ids=[foreign_participant.id]))
