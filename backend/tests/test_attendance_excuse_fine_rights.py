"""«Entschuldigen» (Dashboard, POST /protocols/{id}/attendance/{person}/excuse) und offene Bussen.

Die Route verlangt meetings.edit und entfernte bisher zusätzlich die offene Anwesenheitsbusse der
Person - hart und ohne Audit-Eintrag. Bussen löschen ist aber fines.manage plus gebuchtes Modul
«finance» (DELETE /fines/{id}); die Standardrolle «writer» hat fines.manage nicht. Ohne dieses Recht
bleibt die Busse deshalb stehen (die Kasse entscheidet), mit dem Recht wird sie wie bisher entfernt
und das Löschen auditiert.
"""
from __future__ import annotations

from sqlalchemy import select, text

from app.api.routes import protocols as protocol_routes
from app.models import AttendanceFine
from app.schemas.protocol import AttendanceExcusePayload
from tests.factories import (
    make_current_user,
    make_finance_account,
    make_fine,
    make_participant,
    make_protocol,
    make_protocol_element,
    make_protocol_element_block,
    make_template,
    make_tenant,
)


def _setup(db, name: str):
    tenant = make_tenant(db, name)
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, status="durchgeführt")
    person = make_participant(db, tenant.id, "Abwesend")
    element = make_protocol_element(db, protocol.id)
    make_protocol_element_block(
        db,
        element.id,
        {"attendance_entries": [{"participant_id": person.id, "participant_name": "Abwesend", "status": "absent"}]},
        element_type_code="attendance",
    )
    account = make_finance_account(db, tenant.id)
    fine = make_fine(db, protocol.id, account.id, fine_type="absent", participant_name_snapshot="Abwesend")
    fine.participant_id = person.id
    db.flush()
    return tenant, protocol, person, fine


def _fine_exists(db, fine_id: int) -> bool:
    return db.scalar(select(AttendanceFine.id).where(AttendanceFine.id == fine_id)) is not None


def test_excuse_without_fines_manage_keeps_the_fine(db):
    tenant, protocol, person, fine = _setup(db, "Entschuldigen ohne Kasse")
    writer = make_current_user(tenant.id, role="writer")
    assert "fines.manage" not in writer.permissions

    result = protocol_routes.excuse_participant(protocol.public_id, person.public_id, AttendanceExcusePayload(), db=db, user=writer)

    assert _fine_exists(db, fine.id)
    # Die Oberfläche sagt, dass die Busse stehen bleibt
    assert result["fines_kept"] == 1


def test_excuse_without_finance_write_access_keeps_the_fine(db):
    tenant, protocol, person, fine = _setup(db, "Entschuldigen Finanzen nur lesend")
    admin = make_current_user(tenant.id, role="admin", features=frozenset())

    protocol_routes.excuse_participant(protocol.public_id, person.public_id, AttendanceExcusePayload(), db=db, user=admin)

    assert _fine_exists(db, fine.id)


def test_excuse_with_fines_manage_removes_and_audits_the_fine(db):
    tenant, protocol, person, fine = _setup(db, "Entschuldigen mit Kasse")
    fine_id = fine.id
    admin = make_current_user(tenant.id, role="admin")

    protocol_routes.excuse_participant(protocol.public_id, person.public_id, AttendanceExcusePayload(), db=db, user=admin)

    assert not _fine_exists(db, fine_id)
    assert db.scalar(
        text("SELECT count(*) FROM audit_log WHERE action = 'fine.deleted' AND entity_id = :id"), {"id": fine_id}
    ) == 1


def test_excuse_removes_every_pending_fine_of_the_person(db):
    # «late» und «absent» können gleichzeitig offen sein (Index je fine_type)
    tenant, protocol, person, fine = _setup(db, "Entschuldigen zwei Bussen")
    late = make_fine(db, protocol.id, fine.account_id, fine_type="late", participant_name_snapshot="Abwesend")
    late.participant_id = person.id
    db.flush()
    ids = [fine.id, late.id]
    admin = make_current_user(tenant.id, role="admin")

    protocol_routes.excuse_participant(protocol.public_id, person.public_id, AttendanceExcusePayload(), db=db, user=admin)

    assert not any(_fine_exists(db, fine_id) for fine_id in ids)
    assert db.scalar(
        text("SELECT count(*) FROM audit_log WHERE action = 'fine.deleted' AND entity_id = ANY(:ids)"), {"ids": ids}
    ) == 2
