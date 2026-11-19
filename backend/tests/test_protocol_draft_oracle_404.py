"""Nicht lesbare Protokolle (Entwurf ohne meetings.read_drafts, eingeschränkter Leser ohne
Zuordnung) antworten auf allen lesenden Wegen wie eine unbekannte ID: 404 mit derselben Meldung
statt 403 «Protocol not assigned to current reader» (SECURITY-RULES 1.6, Nachtlauf-Review
2026-11-19). Sonst verrät der Statuscode, dass es den Entwurf gibt.

Routen werden wie in den übrigen Route-Tests direkt als Funktionen aufgerufen.
"""
from __future__ import annotations

import uuid
from datetime import date

import pytest
from fastapi import HTTPException

from app.api.routes import documents as documents_route
from app.api.routes import protocol_elements as elements_route
from app.api.routes import protocols as protocols_route
from app.api.routes import todos as todos_route
from app.documents.context import BuildContext, DocumentNotFoundError
from app.models import UserTemplateAccess
from app.services.access_service import AccessService

from tests.factories import (
    make_app_user,
    make_current_user,
    make_protocol,
    make_protocol_element,
    make_protocol_element_block,
    make_protocol_todo,
    make_template,
    make_tenant,
)


@pytest.fixture
def draft(db):
    tenant = make_tenant(db, "Entwurf-Orakel")
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, status="geplant")
    element = make_protocol_element(db, protocol.id)
    block = make_protocol_element_block(db, element.id, {}, element_type_code="todo")
    todo = make_protocol_todo(db, block.id, task="Geheim")
    scoped = make_app_user(db, email=f"scoped-{uuid.uuid4().hex[:6]}@example.com", tenant_id=tenant.id, role_code="reader")
    db.add(UserTemplateAccess(user_id=scoped.id, tenant_id=tenant.id, template_id=template.id))
    db.flush()
    return {
        "tenant": tenant,
        "protocol": protocol,
        "block": block,
        "todo": todo,
        # Leser ohne meetings.read_drafts: sieht nur abgeschlossene Protokolle
        "reader": make_current_user(tenant.id, role="reader"),
        # Eingeschränkter Leser, dem Protokoll nicht zugeordnet
        "scoped": make_current_user(tenant.id, role="reader", user_id=scoped.id),
    }


def _error(call) -> tuple[int, object]:
    with pytest.raises(HTTPException) as info:
        call()
    return info.value.status_code, info.value.detail


ROUTES = {
    "get_protocol": lambda pid, db, user: protocols_route.get_protocol(pid, db=db, user=user),
    "pdf_coverage": lambda pid, db, user: protocols_route.get_protocol_pdf_coverage(pid, db=db, user=user),
    "pending_todos": lambda pid, db, user: protocols_route.get_pending_todos(pid, db=db, user=user),
    "elements": lambda pid, db, user: elements_route.list_protocol_elements(pid, db=db, user=user),
    "block_todos": lambda pid, db, user: todos_route.list_protocol_block_todos(pid, db=db, user=user),
    "exports": lambda pid, db, user: documents_route.list_document_exports(
        protocol_id=pid, document_type=None, limit=20, offset=0, db=db, user=user
    ),
}


@pytest.mark.parametrize("route", sorted(ROUTES))
@pytest.mark.parametrize("who", ["reader", "scoped"])
def test_unreadable_draft_looks_like_an_unknown_protocol(db, draft, route, who):
    call = ROUTES[route]
    user = draft[who]
    hidden = _error(lambda: call(draft["protocol"].public_id, db, user))
    unknown = _error(lambda: call(uuid.uuid4(), db, user))
    assert hidden == unknown
    assert hidden[0] == 404


@pytest.mark.parametrize("who", ["reader", "scoped"])
def test_block_todos_of_an_unreadable_draft_look_like_an_unknown_block(db, draft, who):
    user = draft[who]
    hidden = _error(lambda: todos_route.list_todos(draft["block"].public_id, db=db, user=user))
    unknown = _error(lambda: todos_route.list_todos(uuid.uuid4(), db=db, user=user))
    assert hidden == unknown == (404, "Protocol element block not found")


def test_todo_of_an_unassigned_draft_looks_like_an_unknown_todo(db, draft):
    user = draft["scoped"]
    hidden = _error(lambda: todos_route.get_todo_details(draft["todo"].public_id, db=db, user=user))
    unknown = _error(lambda: todos_route.get_todo_details(uuid.uuid4(), db=db, user=user))
    assert hidden == unknown == (404, "Todo not found")


def test_access_service_block_and_element_checks_answer_404(db, draft):
    access = AccessService()
    block = draft["block"]
    for user in (draft["reader"], draft["scoped"]):
        assert _error(lambda: access.ensure_can_read_protocol(db, user, draft["protocol"].id))[0] == 404
        assert _error(lambda: access.ensure_can_read_protocol_block(db, user, block.id)) == (404, "Protocol block not found")
        assert _error(lambda: access.ensure_can_read_protocol_element(db, user, block.protocol_element_id)) == (
            404, "Protocol element not found",
        )


def test_document_source_options_of_an_unreadable_draft_are_empty_like_unknown(db, draft):
    for user in (draft["reader"], draft["scoped"]):
        for source in ("protocol_elements", "protocol_blocks"):
            hidden = documents_route.list_source_options(source, protocol_id=draft["protocol"].public_id, list_id=None, db=db, user=user)
            unknown = documents_route.list_source_options(source, protocol_id=uuid.uuid4(), list_id=None, db=db, user=user)
            assert hidden == unknown == []


def test_document_engine_treats_an_unreadable_protocol_as_not_found(db, draft):
    ctx = BuildContext(db=db, tenant_id=draft["tenant"].id, language="de", user=draft["reader"], today=date(2026, 1, 1))
    # Wie ein unbekanntes Protokoll (referenceNotFound/404), kein Rechtefehler, der den Entwurf verrät
    with pytest.raises(DocumentNotFoundError):
        ctx.ensure_can_read_protocol(draft["protocol"].id)

def test_readable_protocol_is_still_returned(db, draft):
    writer = make_current_user(draft["tenant"].id)
    assert protocols_route.get_protocol(draft["protocol"].public_id, db=db, user=writer).id == draft["protocol"].public_id
