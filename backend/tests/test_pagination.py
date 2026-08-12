"""Regression tests for the 2026-07-29 pagination sweep: skip/limit must produce
non-overlapping pages, and the finance running balance must stay correct across page
boundaries (this broke silently with the old client-side float-reduce approach)."""
from datetime import date, timedelta

from app.repositories.finance_repository import FinanceRepository
from app.repositories.fines_repository import FinesRepository

from tests.factories import make_finance_account, make_fine, make_protocol, make_template, make_tenant


def test_finance_transactions_pagination_has_no_overlap_and_correct_running_balance(db):
    repo = FinanceRepository()
    tenant = make_tenant(db)
    account = make_finance_account(db, tenant.id)

    from app.schemas.finance import FinanceTransactionCreate

    amounts = [10, -3, 25, -7, 100, -50, 1, 2, 3, 4]
    base_date = date(2026, 1, 1)
    for i, amount in enumerate(amounts):
        repo.create_transaction(
            db, account.id, tenant.id,
            payload=FinanceTransactionCreate(amount=amount, description=f"tx{i}", transaction_date=base_date + timedelta(days=i)),
        )

    all_rows = []
    skip = 0
    page_size = 3
    while True:
        page = repo.list_transactions(db, account.id, skip=skip, limit=page_size)
        if not page:
            break
        all_rows.extend(page)
        skip += page_size

    assert len(all_rows) == len(amounts)
    assert len({row.id for row in all_rows}) == len(amounts)  # no duplicate rows across pages

    running = 0
    expected_running_desc = []
    for amount in amounts:
        running += amount
        expected_running_desc.append(running)
    expected_running_desc.reverse()  # newest first, matching list_transactions' order

    assert [float(row.running_balance) for row in all_rows] == [float(x) for x in expected_running_desc]

    account_after = repo.get_account(db, account.id, tenant_id=tenant.id)
    assert float(account_after.balance) == float(sum(amounts))


def test_fines_pagination_has_no_overlap(db):
    repo = FinesRepository()
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id)
    account = make_finance_account(db, tenant.id)
    created_ids = [make_fine(db, protocol.id, account.id, amount=i).id for i in range(1, 6)]

    page1 = repo.list_fines_for_tenant(db, tenant_id=tenant.id, skip=0, limit=2)
    page2 = repo.list_fines_for_tenant(db, tenant_id=tenant.id, skip=2, limit=2)
    page3 = repo.list_fines_for_tenant(db, tenant_id=tenant.id, skip=4, limit=2)

    seen_ids = [f.id for f in page1] + [f.id for f in page2] + [f.id for f in page3]
    assert sorted(seen_ids) == sorted(created_ids)
    assert len(seen_ids) == len(set(seen_ids))  # no duplicates across pages
