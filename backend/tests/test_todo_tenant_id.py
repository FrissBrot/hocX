"""Jedes Todo gehört fest seinem Mandanten (Migration 0131_todo_tenant_id): Todos mit Block
erhalten tenant_id aus dem Protokoll, Todos ohne Block müssen sie selbst tragen."""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import ProtocolTodo, TodoStatus
from app.schemas.protocol import ProtocolTodoCreate
from app.services.protocol_todo_service import ProtocolTodoService
from tests.factories import (
    make_protocol,
    make_protocol_element,
    make_protocol_element_block,
    make_protocol_todo,
    make_template,
    make_tenant,
)


def _block(db, tenant_id: int):
    protocol = make_protocol(db, tenant_id, make_template(db, tenant_id).id)
    return make_protocol_element_block(db, make_protocol_element(db, protocol.id).id, {}, element_type_code="todo")


def _open_status_id(db) -> int:
    return db.scalar(select(TodoStatus.id).where(TodoStatus.code == "open"))


def test_todo_in_a_protocol_gets_the_protocol_tenant(db):
    tenant = make_tenant(db)
    block = _block(db, tenant.id)

    todo = ProtocolTodoService().create_todo(db, block.id, ProtocolTodoCreate(task="Material", todo_status_id=_open_status_id(db)))

    assert todo.tenant_id == tenant.id
    assert db.scalar(select(ProtocolTodo.tenant_id).where(ProtocolTodo.id == todo.id)) == tenant.id


def test_moving_a_todo_to_another_tenants_block_is_rejected(db):
    tenant, other = make_tenant(db), make_tenant(db)
    todo = make_protocol_todo(db, _block(db, tenant.id).id)
    foreign_block_id = _block(db, other.id).id

    with pytest.raises(IntegrityError, match="passt nicht zum Protokoll"):
        with db.begin_nested():
            todo.protocol_element_block_id = foreign_block_id
            db.flush()


def test_todo_with_a_contradicting_tenant_is_rejected(db):
    tenant, other = make_tenant(db), make_tenant(db)
    block_id = _block(db, tenant.id).id

    with pytest.raises(IntegrityError, match="passt nicht zum Protokoll"):
        with db.begin_nested():
            make_protocol_todo(db, block_id, tenant_id=other.id)


def test_todo_without_protocol_needs_its_own_tenant(db):
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.add(ProtocolTodo(protocol_element_block_id=None, task="Schnell", todo_status_id=_open_status_id(db)))
            db.flush()
