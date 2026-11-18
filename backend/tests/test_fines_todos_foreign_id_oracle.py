"""Kein Existenz-Orakel über Mandanten hinweg (SECURITY-RULES 1.1/1.6) bei Anwesenheitsbussen
und Aufgabenblöcken.

AttendanceFine und ProtocolElementBlock haben keine eigene tenant_id - ``tenant_id=`` an
public_id_service ist dort wirkungslos. Die Routen lösten die ID deshalb mandantenübergreifend auf
und meldeten eine fremde Busse bzw. einen fremden Block anders als eine unbekannte ID (andere
404-Meldung bzw. 403 statt 404). Ohne RLS (Superuser, Hintergrund, Fehlkonfiguration) liess sich
so prüfen, ob eine ID bei einem anderen Verein existiert. Erwartet: fremd = unbekannt."""
import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.api.routes import fines as fine_routes
from app.api.routes import todos as todo_routes
from app.models import AttendanceFine
from app.schemas.fines import CollectFinePayload
from app.schemas.protocol import ProtocolTodoCreate
from tests.factories import (
    make_current_user,
    make_finance_account,
    make_fine,
    make_protocol,
    make_protocol_element,
    make_protocol_element_block,
    make_template,
    make_tenant,
)


def _error(call) -> tuple[int, object]:
    with pytest.raises(HTTPException) as exc:
        call()
    return exc.value.status_code, exc.value.detail


def _foreign_fine(db, status: str = "pending") -> AttendanceFine:
    tenant = make_tenant(db, "Fremder Verein (Bussen)")
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, protocol_number="F-1")
    account = make_finance_account(db, tenant.id)
    fine = make_fine(db, protocol_id=protocol.id, account_id=account.id, amount=Decimal("5.00"))
    fine.status = status
    if status == "deleted":
        fine.delete_comment = "Erfassungsfehler"
    db.flush()
    return fine


def _own_user(db):
    tenant = make_tenant(db, "Eigener Verein (Bussen)")
    return make_current_user(tenant.id, role="admin")


@pytest.mark.parametrize(
    ("action", "status"),
    [
        ("delete", "pending"),
        ("collect", "pending"),
        ("restore", "deleted"),
        ("reopen", "collected"),
    ],
)
def test_foreign_fine_answers_like_an_unknown_fine(db, action, status):
    user = _own_user(db)
    fine = _foreign_fine(db, status)

    def call(fine_id):
        if action == "delete":
            return lambda: fine_routes.delete_fine(fine_id, payload=None, db=db, user=user)
        if action == "collect":
            return lambda: fine_routes.collect_fine(fine_id, payload=CollectFinePayload(), db=db, user=user)
        if action == "restore":
            return lambda: fine_routes.restore_fine(fine_id, db=db, user=user)
        return lambda: fine_routes.reopen_fine(fine_id, db=db, user=user)

    assert _error(call(fine.public_id)) == _error(call(uuid.uuid4()))
    db.expire_all()
    assert db.get(AttendanceFine, fine.id).status == status


def _foreign_todo_block(db):
    tenant = make_tenant(db, "Fremder Verein (Pendenzen)")
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, protocol_number="F-2")
    element = make_protocol_element(db, protocol.id)
    return make_protocol_element_block(db, element.id, {}, element_type_code="todo")


def test_foreign_todo_block_list_answers_like_an_unknown_block(db):
    user = _own_user(db)
    block = _foreign_todo_block(db)

    def call(block_id):
        return lambda: todo_routes.list_todos(block_id, db=db, user=user)

    assert _error(call(block.public_id)) == _error(call(uuid.uuid4()))


def test_foreign_todo_block_create_answers_like_an_unknown_block(db):
    user = _own_user(db)
    block = _foreign_todo_block(db)

    def call(block_id):
        return lambda: todo_routes.create_todo(block_id, ProtocolTodoCreate(task="Fremd"), db=db, user=user)

    assert _error(call(block.public_id)) == _error(call(uuid.uuid4()))
