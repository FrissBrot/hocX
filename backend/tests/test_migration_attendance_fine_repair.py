"""Migration 0163: Anwesenheitsbussen offener Protokolle an die Anwesenheit angleichen
(fehlende anlegen, nicht mehr passende offene löschen); abgeschlossene Protokolle,
eingezogene Bussen und Blöcke ohne Bussen bleiben unverändert."""
from __future__ import annotations

import importlib.util
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import AttendanceFine
from app.schemas.fines import FineTariffUpdate
from app.services import fine_tariff_service
from tests.factories import (
    make_finance_account,
    make_participant,
    make_protocol,
    make_protocol_element,
    make_protocol_element_block,
    make_template,
    make_tenant,
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def migration(db, monkeypatch):
    spec = importlib.util.spec_from_file_location("migration_0163", BACKEND_ROOT / "alembic/versions/0163_attendance_fine_repair.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.op, "get_bind", lambda: db.connection(), raising=False)
    return module


def _fine(db, protocol, participant, account, fine_type, status="pending"):
    fine = AttendanceFine(
        protocol_id=protocol.id, participant_id=participant.id, participant_name_snapshot=participant.display_name,
        fine_type=fine_type, amount=Decimal("1"), account_id=account.id, status=status,
    )
    db.add(fine)
    db.flush()
    return fine


def _fines(db, protocol):
    rows = db.execute(select(AttendanceFine).where(AttendanceFine.protocol_id == protocol.id)).scalars()
    return sorted((fine.participant_id, fine.fine_type, fine.status, fine.amount) for fine in rows)


def _attendance(db, protocol, entries, fines_enabled=True):
    element = make_protocol_element(db, protocol.id)
    make_protocol_element_block(
        db, element.id,
        {"fines_enabled": fines_enabled, "attendance_entries": [
            {"participant_id": participant.id, "participant_name": participant.display_name, "status": status}
            for participant, status in entries
        ]},
        sort_index=0, element_type_code="attendance",
    )


def test_repairs_open_protocols_only(db, migration):
    tenant = make_tenant(db, "Bussen")
    account = make_finance_account(db, tenant.id)
    fine_tariff_service.update_tariff(
        db, tenant.id, FineTariffUpdate(account_id=account.public_id, amount_late=Decimal("2"), amount_absent=Decimal("5"))
    )
    template = make_template(db, tenant.id)
    late, absent, excused, present, collected = (make_participant(db, tenant.id, name) for name in ("Spät", "Weg", "Entschuldigt", "Da", "Bezahlt"))

    open_protocol = make_protocol(db, tenant.id, template.id, protocol_number="P-1", status="durchgeführt")
    _attendance(db, open_protocol, [(late, "late"), (absent, "absent"), (excused, "excused"), (present, "present"), (collected, "present")])
    _fine(db, open_protocol, excused, account, "late")  # falsch stehen geblieben
    _fine(db, open_protocol, absent, account, "late")  # falscher Typ
    _fine(db, open_protocol, collected, account, "late", status="collected")  # eingezogen: bleibt

    closed = make_protocol(db, tenant.id, template.id, protocol_number="P-2", status="abgeschlossen")
    _attendance(db, closed, [(late, "late")])
    disabled = make_protocol(db, tenant.id, template.id, protocol_number="P-3")
    _attendance(db, disabled, [(late, "late")], fines_enabled=False)

    migration.upgrade()
    db.expire_all()

    assert _fines(db, open_protocol) == sorted([
        (late.id, "late", "pending", Decimal("2.00")),
        (absent.id, "absent", "pending", Decimal("5.00")),
        (collected.id, "late", "collected", Decimal("1.00")),
    ])
    assert _fines(db, closed) == []
    assert _fines(db, disabled) == []

    # Zweiter Lauf ändert nichts mehr
    migration.upgrade()
    db.expire_all()
    assert len(_fines(db, open_protocol)) == 3


def test_ignores_participants_of_other_tenants(db, migration):
    tenant = make_tenant(db, "A")
    other = make_tenant(db, "B")
    account = make_finance_account(db, tenant.id)
    fine_tariff_service.update_tariff(db, tenant.id, FineTariffUpdate(account_id=account.public_id, amount_late=Decimal("2")))
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id)
    stranger = make_participant(db, other.id, "Fremd")
    _attendance(db, protocol, [(stranger, "late")])

    migration.upgrade()
    db.expire_all()

    assert _fines(db, protocol) == []
