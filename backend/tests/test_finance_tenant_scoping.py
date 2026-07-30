"""Regression tests for the cross-tenant IDOR class of bug fixed in the 2026-07-26
security audit (K1-K4): finance routes must never let one tenant read/modify another
tenant's accounts or transactions just by guessing an id."""
from app.repositories.finance_repository import FinanceRepository
from app.schemas.finance import FinanceTransactionCreate, FinanceTransactionUpdate

from tests.factories import make_finance_account, make_tenant


def test_get_account_returns_none_for_wrong_tenant(db):
    repo = FinanceRepository()
    tenant_a = make_tenant(db, "Tenant A")
    tenant_b = make_tenant(db, "Tenant B")
    account = make_finance_account(db, tenant_a.id)

    assert repo.get_account(db, account.id, tenant_id=tenant_a.id) is not None
    assert repo.get_account(db, account.id, tenant_id=tenant_b.id) is None


def test_update_transaction_is_scoped_to_owning_tenant(db):
    repo = FinanceRepository()
    tenant_a = make_tenant(db, "Tenant A")
    tenant_b = make_tenant(db, "Tenant B")
    account = make_finance_account(db, tenant_a.id)
    tx = repo.create_transaction(
        db, account.id,
        payload=FinanceTransactionCreate(amount=10, description="test", transaction_date="2026-01-01"),
    )

    # Tenant B must not be able to touch tenant A's transaction.
    result = repo.update_transaction(db, tx.id, tenant_id=tenant_b.id, payload=FinanceTransactionUpdate(amount=999))
    assert result is None

    result = repo.update_transaction(db, tx.id, tenant_id=tenant_a.id, payload=FinanceTransactionUpdate(amount=20))
    assert result is not None
    assert float(result.amount) == 20


def test_delete_transaction_is_scoped_to_owning_tenant(db):
    repo = FinanceRepository()
    tenant_a = make_tenant(db, "Tenant A")
    tenant_b = make_tenant(db, "Tenant B")
    account = make_finance_account(db, tenant_a.id)
    from app.schemas.finance import FinanceTransactionCreate

    tx = repo.create_transaction(
        db, account.id,
        payload=FinanceTransactionCreate(amount=10, description="test", transaction_date="2026-01-01"),
    )

    assert repo.delete_transaction(db, tx.id, tenant_id=tenant_b.id) is False
    assert repo.delete_transaction(db, tx.id, tenant_id=tenant_a.id) is True
