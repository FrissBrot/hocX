"""Pendenz mit unbekanntem Status (Bug-Bounty 2026-11-23, pendenzen-bussen/fehlerbehandlung).

todo_status.id ist SMALLINT. POST /todos bzw. /protocol-element-blocks/{id}/todos mit einer
unbekannten todo_status_id scheiterte erst beim INSERT (ForeignKeyViolation), Werte über 32767
schon beim Nachschlagen des Status («smallint out of range») - auch in PATCH /protocol-todos.
Antwort jeweils 400 plus Eintrag im Fehlerprotokoll, obwohl nur die Eingabe ungültig war."""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.routes import todos as todos_route
from app.schemas.protocol import ProtocolTodoCreate, ProtocolTodoUpdate
from app.services.protocol_todo_service import ProtocolTodoService
from tests.factories import make_current_user, make_tenant


@pytest.mark.parametrize("schema", [ProtocolTodoCreate, ProtocolTodoUpdate])
@pytest.mark.parametrize("status_id", [0, 32_768, 2**40])
def test_status_id_outside_smallint_is_rejected_by_the_schema(schema, status_id):
    with pytest.raises(ValidationError):
        schema.model_validate({"task": "x", "todo_status_id": status_id})


def test_create_with_unknown_status_is_an_expected_error(db):
    tenant = make_tenant(db, "Status unbekannt")
    user = make_current_user(tenant.id, role="admin")

    with pytest.raises(HTTPException) as exc_info:
        todos_route.create_standalone_todo(ProtocolTodoCreate(task="x", todo_status_id=1000), db=db, user=user)

    assert exc_info.value.status_code == 400
    # ValueError = kuratiert, nicht ins Fehlerprotokoll (main.py prüft __cause__)
    assert isinstance(exc_info.value.__cause__, ValueError)


def test_create_and_patch_with_known_status_still_work(db):
    tenant = make_tenant(db, "Status bekannt")
    user = make_current_user(tenant.id, role="admin")

    created = todos_route.create_standalone_todo(ProtocolTodoCreate(task="x", todo_status_id=3), db=db, user=user)
    assert created.todo_status_id == 3 and created.completed_at is not None

    todo = ProtocolTodoService().create_standalone_todo(db, tenant.id, ProtocolTodoCreate(task="y"))
    db.flush()
    patched = todos_route.patch_todo(todo.public_id, ProtocolTodoUpdate(todo_status_id=2), db=db, user=user)
    assert patched.todo_status_id == 2
