"""Protokoll löschen (meetings.edit) darf keine Anwesenheitsbussen mitreissen.

attendance_fine.protocol_id ist ON DELETE CASCADE: Wer ein noch offenes Protokoll löscht, löschte
damit bisher auch dessen Bussen - offene wie bereits einkassierte (die Kassenbuchung bleibt dann
ohne Busse zurück). Bussen ändern/löschen ist aber fines.manage (+ Modul «finance»); die
Standardrolle «writer» darf Protokolle löschen, Bussen nur lesen (RBAC_ARCHITECTURE_PROPOSAL).
Ohne fines.manage lehnt das Löschen deshalb mit 409 ab, solange das Protokoll Bussen hat.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.routes import protocols as protocol_routes
from app.models import AttendanceFine, Protocol
from app.schemas.deletion import DeletionRequest
from tests.factories import (
    make_current_user,
    make_finance_account,
    make_fine,
    make_protocol,
    make_template,
    make_tenant,
)


def _protocol_with_fine(db, name: str, *, collected: bool = False):
    tenant = make_tenant(db, name)
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, status="durchgeführt")
    account = make_finance_account(db, tenant.id)
    fine = make_fine(db, protocol.id, account.id, fine_type="absent")
    if collected:
        fine.status = "collected"
    db.flush()
    return tenant, protocol, fine


@pytest.mark.parametrize("collected", [False, True])
def test_writer_cannot_delete_protocol_with_fines(db, collected):
    tenant, protocol, fine = _protocol_with_fine(db, f"Löschen mit Bussen {collected}", collected=collected)
    fine_id = fine.id
    writer = make_current_user(tenant.id, role="writer")
    assert "fines.manage" not in writer.permissions

    with pytest.raises(HTTPException) as denied:
        protocol_routes.delete_protocol(protocol.public_id, db=db, user=writer)
    assert denied.value.status_code == 409
    with pytest.raises(HTTPException) as denied_selection:
        protocol_routes.delete_protocol_with_selection(protocol.public_id, DeletionRequest(), db=db, user=writer)
    assert denied_selection.value.status_code == 409

    assert db.scalar(select(AttendanceFine.id).where(AttendanceFine.id == fine_id)) == fine_id


def test_fines_manager_can_delete_protocol_with_fines(db):
    tenant, protocol, _ = _protocol_with_fine(db, "Löschen mit Kasse")
    protocol_id = protocol.id
    admin = make_current_user(tenant.id, role="admin")

    protocol_routes.delete_protocol(protocol.public_id, db=db, user=admin)

    assert db.scalar(select(Protocol.id).where(Protocol.id == protocol_id)) is None


def test_writer_can_delete_protocol_without_fines(db):
    tenant = make_tenant(db, "Löschen ohne Bussen")
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, status="durchgeführt")
    protocol_id = protocol.id

    protocol_routes.delete_protocol(protocol.public_id, db=db, user=make_current_user(tenant.id, role="writer"))

    assert db.scalar(select(Protocol.id).where(Protocol.id == protocol_id)) is None
