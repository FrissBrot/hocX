"""Todo-Notizen und verknüpfte Dateien (Migration 0128).

Nur über GET/PUT /protocol-todos/{id}/details erreichbar - Liste, Übersicht und Exporte
(ProtocolTodoRead/TodoListItem) enthalten sie bewusst nicht.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.routes import todos as todos_route
from app.models.entities import StoredFile
from app.schemas.protocol import ProtocolTodoCreate, TodoDetailsUpdate
from app.services.protocol_todo_service import ProtocolTodoService

from tests.factories import make_current_user, make_tenant

service = ProtocolTodoService()


def _todo(db, tenant_id: int):
    todo = service.create_standalone_todo(db, tenant_id, ProtocolTodoCreate(task="Mit Notiz", todo_status_id=1))
    db.flush()
    return todo


def _file(db, tenant_id: int, name: str = "plan.pdf") -> StoredFile:
    row = StoredFile(tenant_id=tenant_id, original_name=name, mime_type="application/pdf", storage_path=f"test-todo/{name}")
    db.add(row)
    db.flush()
    return row


def test_notes_and_files_round_trip(db):
    tenant = make_tenant(db, "Tenant Details")
    todo = _todo(db, tenant.id)
    first, second = _file(db, tenant.id, "a.pdf"), _file(db, tenant.id, "b.pdf")
    writer = make_current_user(tenant.id)

    saved = todos_route.put_todo_details(
        todo.public_id, TodoDetailsUpdate(notes="**Wichtig**\n\n- Punkt", file_ids=[second.public_id, first.public_id]),
        db=db, user=writer,
    )

    assert saved.notes == "**Wichtig**\n\n- Punkt"
    assert [item.original_name for item in saved.files] == ["b.pdf", "a.pdf"]
    assert saved.files[0].content_url == f"/api/stored-files/{second.public_id}/content"

    loaded = todos_route.get_todo_details(todo.public_id, db=db, user=make_current_user(tenant.id, role="reader"))
    assert loaded == saved

    # Teil-Update: nur Notizen ändern lässt die Dateien stehen
    notes_only = todos_route.put_todo_details(todo.public_id, TodoDetailsUpdate(notes="  "), db=db, user=writer)
    assert notes_only.notes == ""
    assert len(notes_only.files) == 2


def test_details_stay_out_of_list_items(db):
    tenant = make_tenant(db, "Tenant Liste")
    todo = _todo(db, tenant.id)
    todos_route.put_todo_details(
        todo.public_id, TodoDetailsUpdate(notes="Geheim", file_ids=[_file(db, tenant.id).public_id]),
        db=db, user=make_current_user(tenant.id),
    )

    item = next(row for row in service.list_todos_for_tenant(db, tenant.id) if row.id == todo.public_id)
    dumped = item.model_dump()
    assert "notes" not in dumped
    assert "files" not in dumped


def test_foreign_tenant_file_is_rejected(db):
    tenant = make_tenant(db, "Tenant Eigen")
    other = make_tenant(db, "Tenant Fremd")
    todo = _todo(db, tenant.id)

    with pytest.raises(HTTPException) as error:
        todos_route.put_todo_details(
            todo.public_id, TodoDetailsUpdate(file_ids=[_file(db, other.id).public_id]), db=db, user=make_current_user(tenant.id),
        )

    assert error.value.status_code == 400


def test_reader_cannot_write_and_foreign_tenant_cannot_read(db):
    tenant = make_tenant(db, "Tenant Rechte")
    other = make_tenant(db, "Tenant Andere")
    todo = _todo(db, tenant.id)

    with pytest.raises(HTTPException) as write_error:
        todos_route.put_todo_details(todo.public_id, TodoDetailsUpdate(notes="x"), db=db, user=make_current_user(tenant.id, role="reader"))
    with pytest.raises(HTTPException) as read_error:
        todos_route.get_todo_details(todo.public_id, db=db, user=make_current_user(other.id))

    assert write_error.value.status_code == 403
    assert read_error.value.status_code == 404


def test_deleting_file_removes_link(db):
    tenant = make_tenant(db, "Tenant Löschen")
    todo = _todo(db, tenant.id)
    stored = _file(db, tenant.id)
    writer = make_current_user(tenant.id)
    todos_route.put_todo_details(todo.public_id, TodoDetailsUpdate(file_ids=[stored.public_id]), db=db, user=writer)

    db.delete(stored)
    db.flush()

    assert todos_route.get_todo_details(todo.public_id, db=db, user=writer).files == []
