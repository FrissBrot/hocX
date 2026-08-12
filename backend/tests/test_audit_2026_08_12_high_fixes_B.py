"""Regression tests for two HIGH findings from the 2026-08-12 full audit.

H5: GET /protocol-todos/{id}/due-events had no tenant/access check at all (unlike its
sibling routes patch_todo/delete_todo/accept_todo_tracked_change in the same file),
letting any authenticated user read another tenant's todo_due_event_tag/next_event_id
by guessing a todo_id.

H6: GET /participants/{id}/templates was gated by require_writer, but its handler body
has a dead "restricted reader" branch that can never run because require_writer already
rejects every reader-role account before the handler executes - making the endpoint
completely unreachable for participant/reader accounts.

Route functions are called directly as plain Python callables (bypassing Depends/ASGI/
auth entirely - FastAPI decorators don't change how a function behaves when invoked
directly), matching the pattern used by test_protocol_element_list_snapshot_routes.py
and test_audit_2026_08_12_critical_fixes.py.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.routes import participants as participants_route
from app.api.routes import todos as todos_route
from app.services.participant_service import ParticipantService

from tests.factories import (
    make_app_user,
    make_current_user,
    make_participant,
    make_protocol,
    make_protocol_element,
    make_protocol_element_block,
    make_protocol_todo,
    make_template,
    make_tenant,
    make_user_tenant_role,
)

participant_service = ParticipantService()


# --- H5: due-events route leaked cross-tenant todo data ---------------------------------


def test_h5_due_events_rejects_foreign_tenant_todo(db):
    tenant_a = make_tenant(db, "Tenant A")
    tenant_b = make_tenant(db, "Tenant B")
    template_a = make_template(db, tenant_a.id)
    protocol_a = make_protocol(db, tenant_a.id, template_a.id)
    element_a = make_protocol_element(db, protocol_a.id)
    block_a = make_protocol_element_block(db, element_a.id, configuration_snapshot_json={})
    todo_a = make_protocol_todo(db, block_a.id, task="Secret Task")

    # ensure_can_read_todo -> ensure_can_read_protocol rejects this as 403 "not assigned
    # to current reader" (same convention as every other route reusing that guard, e.g.
    # test_protocol_element_list_snapshot_routes.py) rather than 404 - the point of the
    # regression test is that the cross-tenant data is no longer returned at all.
    user_b = make_current_user(tenant_b.id, role="reader", user_id=2)
    with pytest.raises(HTTPException) as exc_info:
        todos_route.get_todo_due_events(todo_a.id, db=db, user=user_b)
    assert exc_info.value.status_code == 403


def test_h5_due_events_still_works_for_same_tenant_user(db):
    tenant_a = make_tenant(db, "Tenant A")
    template_a = make_template(db, tenant_a.id)
    protocol_a = make_protocol(db, tenant_a.id, template_a.id)
    element_a = make_protocol_element(db, protocol_a.id)
    block_a = make_protocol_element_block(db, element_a.id, configuration_snapshot_json={})
    todo_a = make_protocol_todo(db, block_a.id, task="Normal Task")

    user_a = make_current_user(tenant_a.id, role="reader", user_id=1)
    result = todos_route.get_todo_due_events(todo_a.id, db=db, user=user_a)
    assert "events" in result
    assert "next_event_id" in result


# --- H6: /participants/{id}/templates unreachable for reader/participant accounts -------


def test_h6_reader_can_now_reach_endpoint_for_own_participant(db):
    tenant = make_tenant(db)
    template1 = make_template(db, tenant.id, name="Template 1")
    template2 = make_template(db, tenant.id, name="Template 2")

    reader_user = make_app_user(db, email="reader@example.com")
    make_user_tenant_role(db, reader_user.id, tenant.id, role_code="reader")
    participant_reader = make_participant(db, tenant.id, display_name="Reader Participant")
    participant_reader.app_user_id = reader_user.id
    db.flush()

    participant_other = make_participant(db, tenant.id, display_name="Other Participant")

    # Assigning templates through the service also syncs UserTemplateAccess for the
    # linked app user (same as production), which is what flips _is_restricted_reader
    # to True for participant_reader's account.
    participant_service.replace_templates_for_participant(db, participant_reader.id, [template1.id])
    participant_service.replace_templates_for_participant(db, participant_other.id, [template1.id, template2.id])

    reader_cu = make_current_user(tenant.id, role="reader", user_id=reader_user.id)

    # Previously this raised HTTPException(403, "Writer role required") because the route
    # was gated by require_writer. It must now succeed for a reader account.
    result_own = participants_route.list_participant_templates(participant_reader.id, db=db, user=reader_cu)
    assert {t.id for t in result_own} == {template1.id}


def test_h6_restricted_reader_scoped_when_querying_other_participant(db):
    tenant = make_tenant(db)
    template1 = make_template(db, tenant.id, name="Template 1")
    template2 = make_template(db, tenant.id, name="Template 2")

    reader_user = make_app_user(db, email="reader2@example.com")
    make_user_tenant_role(db, reader_user.id, tenant.id, role_code="reader")
    participant_reader = make_participant(db, tenant.id, display_name="Reader Participant 2")
    participant_reader.app_user_id = reader_user.id
    db.flush()

    participant_other = make_participant(db, tenant.id, display_name="Other Participant 2")

    participant_service.replace_templates_for_participant(db, participant_reader.id, [template1.id])
    participant_service.replace_templates_for_participant(db, participant_other.id, [template1.id, template2.id])

    reader_cu = make_current_user(tenant.id, role="reader", user_id=reader_user.id)

    # The reader's own account is only assigned template1. Querying a *different*
    # participant's templates (who is assigned template1 AND template2) must still be
    # scoped down to what this reader themself can read - template2 must not leak.
    result_other = participants_route.list_participant_templates(participant_other.id, db=db, user=reader_cu)
    assert {t.id for t in result_other} == {template1.id}


def test_h6_unrestricted_reader_sees_full_list(db):
    tenant = make_tenant(db)
    template1 = make_template(db, tenant.id, name="Template 1")
    template2 = make_template(db, tenant.id, name="Template 2")
    participant_other = make_participant(db, tenant.id, display_name="Other Participant 3")
    participant_service.replace_templates_for_participant(db, participant_other.id, [template1.id, template2.id])

    # A reader with no participant link and no scoped UserTemplateAccess rows is an
    # "unrestricted reader" - full read access within their own tenant, same as every
    # other route using AccessService's restricted-reader pattern (fines.py, todos.py etc).
    plain_reader_user = make_app_user(db, email="plain-reader@example.com")
    make_user_tenant_role(db, plain_reader_user.id, tenant.id, role_code="reader")
    plain_reader_cu = make_current_user(tenant.id, role="reader", user_id=plain_reader_user.id)

    result = participants_route.list_participant_templates(participant_other.id, db=db, user=plain_reader_cu)
    assert {t.id for t in result} == {template1.id, template2.id}


def test_h6_writer_still_works_unfiltered(db):
    tenant = make_tenant(db)
    template1 = make_template(db, tenant.id, name="Template 1")
    template2 = make_template(db, tenant.id, name="Template 2")
    participant_other = make_participant(db, tenant.id, display_name="Other Participant 4")
    participant_service.replace_templates_for_participant(db, participant_other.id, [template1.id, template2.id])

    writer_cu = make_current_user(tenant.id, role="writer", user_id=999)
    result = participants_route.list_participant_templates(participant_other.id, db=db, user=writer_cu)
    assert {t.id for t in result} == {template1.id, template2.id}
