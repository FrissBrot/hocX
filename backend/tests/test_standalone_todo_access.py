"""Zugriff auf Standalone-Todos (POST /todos, ohne Protokollblock).

AccessService.ensure_can_read_todo lehnte bisher jedes Todo ohne Protokoll mit 404 ab,
obwohl patch_todo/delete_todo Standalone-Todos ausdruecklich als bearbeitbar behandeln -
Abhaken in der Todo-Liste (Desktop und Mobile), Bearbeiten und Loeschen schlugen fehl.
Jetzt entscheidet der Mandant; fremde Mandanten bekommen weiterhin 404.

Routen werden wie in den uebrigen Route-Tests direkt als Funktionen aufgerufen.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.routes import todos as todos_route
from app.schemas.protocol import ProtocolTodoCreate, ProtocolTodoUpdate
from app.services.protocol_todo_service import ProtocolTodoService

from tests.factories import make_current_user, make_tenant

service = ProtocolTodoService()


def _standalone_todo(db, tenant_id: int):
    todo = service.create_standalone_todo(db, tenant_id, ProtocolTodoCreate(task="Standalone", todo_status_id=1))
    db.flush()
    return todo


def test_writer_can_complete_own_tenant_standalone_todo(db):
    tenant = make_tenant(db, "Tenant Standalone")
    todo = _standalone_todo(db, tenant.id)

    result = todos_route.patch_todo(todo.public_id, ProtocolTodoUpdate(todo_status_id=3), db=db, user=make_current_user(tenant.id))

    assert result.todo_status_id == 3


def test_due_events_work_for_own_tenant_standalone_todo(db):
    tenant = make_tenant(db, "Tenant Standalone")
    todo = _standalone_todo(db, tenant.id)

    result = todos_route.get_todo_due_events(todo.public_id, db=db, user=make_current_user(tenant.id, role="reader"))

    assert result["tag_filter"] is None
    assert "events" in result


def test_foreign_tenant_cannot_touch_standalone_todo(db):
    tenant_a = make_tenant(db, "Tenant A")
    tenant_b = make_tenant(db, "Tenant B")
    todo = _standalone_todo(db, tenant_a.id)
    user_b = make_current_user(tenant_b.id)

    with pytest.raises(HTTPException) as patch_error:
        todos_route.patch_todo(todo.public_id, ProtocolTodoUpdate(todo_status_id=3), db=db, user=user_b)
    with pytest.raises(HTTPException) as delete_error:
        todos_route.delete_todo(todo.public_id, db=db, user=user_b)

    assert patch_error.value.status_code == 404
    assert delete_error.value.status_code == 404
