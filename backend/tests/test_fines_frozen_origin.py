"""Audit MAIN-BE-002: Offene Bussen aus abgeschlossenen Protokollen lassen sich in einem
offenen Folgeprotokoll einkassieren; das abgeschlossene Protokoll selbst nimmt keine
Inkassi mehr auf."""
from datetime import date
from decimal import Decimal

from app.models import AttendanceFine, FinanceTransaction
from app.repositories.fines_repository import FinesRepository
from tests.factories import make_finance_account, make_fine, make_protocol, make_template, make_tenant


def _setup(db):
    tenant = make_tenant(db, "Tenant (BE-002)")
    template = make_template(db, tenant.id)
    origin = make_protocol(db, tenant.id, template.id, protocol_number="P-A", protocol_date=date(2026, 1, 1), status="abgeschlossen")
    following = make_protocol(db, tenant.id, template.id, protocol_number="P-B", protocol_date=date(2026, 2, 1))
    account = make_finance_account(db, tenant.id)
    fine = make_fine(db, protocol_id=origin.id, account_id=account.id, amount=Decimal("5.00"))
    return tenant, origin, following, fine


def test_collect_pending_fine_from_frozen_origin_in_open_protocol(db):
    tenant, origin, following, fine = _setup(db)

    result = FinesRepository().collect_fine(db, fine.id, tenant.id, actor_user_id=1, collecting_protocol_id=following.id)

    assert result is not None
    row = db.get(AttendanceFine, fine.id)
    assert row.status == "collected"
    assert row.closed_in_protocol_id == following.id
    assert db.get(FinanceTransaction, row.collected_transaction_id).protocol_id == following.id


def test_collect_pending_fine_from_frozen_origin_without_context_uses_next_open(db):
    tenant, _, following, fine = _setup(db)

    assert FinesRepository().collect_fine(db, fine.id, tenant.id, actor_user_id=1) is not None
    assert db.get(AttendanceFine, fine.id).closed_in_protocol_id == following.id


def test_collect_in_frozen_protocol_is_rejected(db):
    tenant, origin, following, fine = _setup(db)
    repo = FinesRepository()

    # Im eingefrorenen Ursprungsprotokoll selbst
    assert repo.collect_fine(db, fine.id, tenant.id, actor_user_id=1, collecting_protocol_id=origin.id) is None
    # In einem anderen, ebenfalls abgeschlossenen Protokoll
    following.status = "abgeschlossen"
    db.flush()
    assert repo.collect_fine(db, fine.id, tenant.id, actor_user_id=1, collecting_protocol_id=following.id) is None
    assert db.get(AttendanceFine, fine.id).status == "pending"
