"""Audit MAIN-BE-017: Bussen- und Buchungslisten lösen public_ids ohne N+1 auf."""
from datetime import date
from decimal import Decimal

from sqlalchemy import event

from app.models import FinanceTransaction
from app.repositories.finance_repository import FinanceRepository
from app.repositories.fines_repository import FinesRepository
from tests.factories import make_finance_account, make_fine, make_protocol, make_template, make_tenant


class _SelectCounter:
    def __init__(self, db):
        self.engine = db.get_bind()
        self.count = 0

    def _listener(self, conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            self.count += 1

    def __enter__(self):
        event.listen(self.engine, "before_cursor_execute", self._listener)
        return self

    def __exit__(self, *exc):
        event.remove(self.engine, "before_cursor_execute", self._listener)


def _tenant_with_fines(db, n: int):
    tenant = make_tenant(db, f"N+1 {n}")
    template = make_template(db, tenant.id)
    account = make_finance_account(db, tenant.id)
    for index in range(n):
        protocol = make_protocol(db, tenant.id, template.id, protocol_number=f"P-{n}-{index}", protocol_date=date(2026, 1, index + 1))
        make_fine(db, protocol_id=protocol.id, account_id=account.id, amount=Decimal("5.00"))
        db.add(FinanceTransaction(account_id=account.id, amount=Decimal("1.00"), description="x", transaction_date=date(2026, 1, 1), protocol_id=protocol.id))
    db.flush()
    db.expire_all()
    return tenant, account


def test_fine_list_query_count_is_independent_of_row_count(db):
    small_tenant, _ = _tenant_with_fines(db, 2)
    large_tenant, _ = _tenant_with_fines(db, 12)
    repo = FinesRepository()

    with _SelectCounter(db) as small:
        assert len(repo.list_fines_for_tenant(db, small_tenant.id)) == 2
    with _SelectCounter(db) as large:
        assert len(repo.list_fines_for_tenant(db, large_tenant.id)) == 12
    assert large.count == small.count


def test_transaction_list_query_count_is_independent_of_row_count(db):
    _, small_account = _tenant_with_fines(db, 2)
    _, large_account = _tenant_with_fines(db, 12)
    repo = FinanceRepository()

    with _SelectCounter(db) as small:
        assert len(repo.list_transactions(db, small_account.id)) == 2
    with _SelectCounter(db) as large:
        assert len(repo.list_transactions(db, large_account.id)) == 12
    assert large.count == small.count
