"""Audit MAIN-BE-008 / MAIN-BE-009: Buchungen einkassierter Bussen und Konten mit
Finanzhistorie sind vor stillen Änderungen geschützt."""
from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.api.routes import finance as finance_routes
from app.models import AttendanceFine, FinanceAccount, FinanceTransaction
from app.repositories.finance_repository import FinanceConflictError, FinanceRepository
from app.repositories.fines_repository import FinesRepository
from app.schemas.finance import FinanceTransactionUpdate
from tests.factories import make_current_user, make_finance_account, make_fine, make_protocol, make_template, make_tenant


def _collected_fine(db):
    tenant = make_tenant(db, "Tenant (BE-008)")
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id)
    account = make_finance_account(db, tenant.id)
    fine = make_fine(db, protocol_id=protocol.id, account_id=account.id, amount=Decimal("5.00"))
    assert FinesRepository().collect_fine(db, fine.id, tenant.id, actor_user_id=1, collecting_protocol_id=protocol.id) is not None
    tx = db.get(FinanceTransaction, db.get(AttendanceFine, fine.id).collected_transaction_id)
    return tenant, account, fine, tx


def test_fine_transaction_cannot_be_deleted_or_changed(db):
    tenant, _, fine, tx = _collected_fine(db)
    repo = FinanceRepository()

    with pytest.raises(FinanceConflictError):
        repo.delete_transaction(db, tx.id, tenant.id)
    with pytest.raises(FinanceConflictError):
        repo.update_transaction(db, tx.id, tenant.id, FinanceTransactionUpdate(amount=Decimal("1.00")))

    assert db.get(FinanceTransaction, tx.id) is not None
    assert db.get(AttendanceFine, fine.id).status == "collected"


def test_fine_transaction_delete_route_returns_409(db):
    tenant, _, _, tx = _collected_fine(db)
    user = make_current_user(tenant.id, role="admin")

    with pytest.raises(HTTPException) as exc:
        finance_routes.delete_transaction(tx.public_id, db=db, user=user)
    assert exc.value.status_code == 409


def test_regular_transaction_still_deletable(db):
    tenant = make_tenant(db, "Tenant (BE-008b)")
    account = make_finance_account(db, tenant.id)
    tx = FinanceTransaction(account_id=account.id, amount=Decimal("3.00"), description="x", transaction_date=date(2026, 1, 1))
    db.add(tx)
    db.flush()

    assert FinanceRepository().delete_transaction(db, tx.id, tenant.id) is True


def test_account_with_history_cannot_be_deleted(db):
    tenant, account, _, _ = _collected_fine(db)

    with pytest.raises(FinanceConflictError):
        FinanceRepository().delete_account(db, account.id, tenant.id)
    assert db.get(FinanceAccount, account.id) is not None

    user = make_current_user(tenant.id, role="admin")
    with pytest.raises(HTTPException) as exc:
        finance_routes.delete_account(account.public_id, db=db, user=user)
    assert exc.value.status_code == 409


def test_empty_account_can_be_deleted(db):
    tenant = make_tenant(db, "Tenant (BE-009)")
    account = make_finance_account(db, tenant.id)

    assert FinanceRepository().delete_account(db, account.id, tenant.id) is True
