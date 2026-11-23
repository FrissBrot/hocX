"""Pendenzen und Aufgabenpakete: ausdrückliches null und Grenzwerte (Bug-Bounty 2026-11-23,
pendenzen-bussen/fehlerbehandlung).

- PATCH /protocol-todos/{id} mit {"task": null}: IntegrityError (NOT NULL), 400 «Todo could
  not be updated» plus Eintrag im Fehlerprotokoll.
- PATCH /protocol-todos/{id} mit {"tags": null}: als JSON-null gespeichert, danach scheiterte
  jede Antwort mit dieser Pendenz an ProtocolTodoRead.tags (Liste) - 500.
- PUT /task-packages/{id} mit {"name": null} oder {"is_active": null}: IntegrityError, gemeldet
  als 409 «Ein Aufgabenpaket mit diesem Namen existiert bereits» plus Fehlerprotokoll.
- Paket-Aufgabe mit sort_index > INTEGER: DataError, 400 plus Fehlerprotokoll.
- Paketname "   " wurde als leerer Name gespeichert.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.api.routes import task_packages as package_routes
from app.api.routes import todos as todos_route
from app.models import ProtocolTodo
from app.schemas.protocol import ProtocolTodoCreate, ProtocolTodoUpdate
from app.schemas.task_package import (
    TaskPackageCreate,
    TaskPackageItemCreate,
    TaskPackageItemUpdate,
    TaskPackageUpdate,
)
from app.services.protocol_todo_service import ProtocolTodoService

from tests.factories import make_current_user, make_tenant

service = ProtocolTodoService()


@pytest.mark.parametrize("field", ["task", "tags"])
def test_todo_update_rejects_explicit_null(field):
    with pytest.raises(ValidationError):
        ProtocolTodoUpdate.model_validate({field: None})


def test_todo_update_null_for_nullable_fields_still_works(db):
    tenant = make_tenant(db, "Pendenzen null")
    todo = service.create_standalone_todo(
        db, tenant.id, ProtocolTodoCreate(task="Standalone", todo_status_id=1, tags=["Lager"], due_marker="bald")
    )
    db.flush()
    user = make_current_user(tenant.id, role="admin")

    result = todos_route.patch_todo(
        todo.public_id, ProtocolTodoUpdate.model_validate({"due_marker": None, "due_date": None}), db=db, user=user
    )

    assert result.task == "Standalone" and result.tags == ["Lager"] and result.due_marker is None
    stored = db.scalar(select(ProtocolTodo).where(ProtocolTodo.id == todo.id))
    assert stored.tags == ["Lager"]


@pytest.mark.parametrize("field", ["name", "is_active"])
def test_package_update_rejects_explicit_null(field):
    with pytest.raises(ValidationError):
        TaskPackageUpdate.model_validate({field: None})


@pytest.mark.parametrize("schema", [TaskPackageCreate, TaskPackageUpdate])
def test_package_name_must_not_be_blank(schema):
    with pytest.raises(ValidationError):
        schema.model_validate({"name": "   "})
    assert schema.model_validate({"name": "  Lager "}).name == "Lager"


@pytest.mark.parametrize("schema", [TaskPackageItemCreate, TaskPackageItemUpdate])
@pytest.mark.parametrize("sort_index", [-1, 2**31])
def test_item_sort_index_is_bounded(schema, sort_index):
    with pytest.raises(ValidationError):
        schema.model_validate({"task": "x", "sort_index": sort_index})


def test_package_routes_still_accept_partial_updates(db):
    tenant = make_tenant(db, "Pakete null")
    admin = make_current_user(tenant.id, role="admin")
    package = package_routes.create_task_package(TaskPackageCreate(name=" Lager "), db=db, user=admin)
    assert package.name == "Lager"

    updated = package_routes.update_task_package(
        package.id, TaskPackageUpdate.model_validate({"description": None, "is_active": False}), db=db, user=admin
    )
    assert (updated.name, updated.is_active, updated.description) == ("Lager", False, None)

    updated = package_routes.create_task_package_item(
        package.id, TaskPackageItemCreate(task="Platz reservieren", sort_index=5), db=db, user=admin
    )
    assert updated.items[0].sort_index == 5
