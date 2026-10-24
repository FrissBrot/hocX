"""Cashflow im Adminportal: Forderungen je Abrechnungsperiode, Kostenfälligkeiten, Übersicht."""
from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.models import CashflowCost, Feature, Plan, StoragePackage, TenantCharge, TenantFeature, TenantStoragePackage
from app.schemas.admin import AdminTenantSubscriptionUpdate
from app.schemas.cashflow import CashflowCostWrite, TenantChargeUpdate
from app.services import cashflow_service
from app.services.admin_tenant_service import AdminTenantService
from tests.factories import make_tenant


def _plan(db, code="cf_basic", monthly=2000, yearly=20000) -> Plan:
    plan = Plan(code=code, name="Cashflow Basic", price_monthly_rp=monthly, price_yearly_rp=yearly)
    db.add(plan)
    db.flush()
    return plan


def _priced_tenant(db, *, start=date(2026, 1, 31), cycle="monthly", discount=0, name="Cashflow Verein"):
    plan = _plan(db)
    tenant = make_tenant(db, name=name)
    tenant.plan_code = plan.code
    tenant.billing_cycle = cycle
    tenant.billing_start_date = start
    tenant.discount_percent = discount
    db.flush()
    return tenant


def _charges(db, tenant):
    return db.scalars(select(TenantCharge).where(TenantCharge.tenant_id == tenant.id).order_by(TenantCharge.period_start)).all()


def test_add_months_keeps_anchor_day_after_short_month():
    assert cashflow_service.add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert cashflow_service.add_months(date(2026, 2, 28), 1, anchor_day=31) == date(2026, 3, 31)
    assert cashflow_service.add_months(date(2024, 2, 29), 12) == date(2025, 2, 28)


def test_sync_creates_monthly_charges_up_to_current_period_and_is_idempotent(db):
    tenant = _priced_tenant(db)
    cashflow_service.sync_charges(db, today=date(2026, 4, 10))
    charges = _charges(db, tenant)
    assert [c.period_start for c in charges] == [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31)]
    assert charges[1].period_end == date(2026, 3, 31)
    assert all(c.amount_rp == 2000 and c.status == "open" for c in charges)
    assert tenant.billing_charged_until == date(2026, 4, 30)

    cashflow_service.sync_charges(db, today=date(2026, 4, 10))
    assert len(_charges(db, tenant)) == 3


def test_charge_amount_includes_addons_discount_and_storage_packages(db):
    tenant = _priced_tenant(db, cycle="yearly", discount=10)
    db.add(Feature(code="cf_addon", name="Zusatz", standalone_price_monthly_rp=500))
    db.add(StoragePackage(code="cf_pkg", name="10 GB", bytes=10, price_monthly_rp=300, price_yearly_rp=3000))
    db.flush()
    db.add(TenantFeature(tenant_id=tenant.id, feature_code="cf_addon"))
    db.add(TenantStoragePackage(tenant_id=tenant.id, package_code="cf_pkg", quantity=2))
    db.flush()

    amount, lines = cashflow_service.compute_tenant_charge(db, tenant)
    # (20000 + 500 * 12) * 0.9 = 23400, plus 2 x 3000 Speicher ohne Rabatt
    assert amount == 23400 + 6000
    assert [line["kind"] for line in lines] == ["plan", "feature", "discount", "storage_package"]
    assert lines[2]["amount_rp"] == -2600


def test_tenant_without_price_advances_cursor_without_backfilling_later(db):
    tenant = make_tenant(db, name="Ohne Plan")
    tenant.billing_start_date = date(2026, 1, 1)
    db.flush()
    cashflow_service.sync_charges(db, today=date(2026, 3, 15))
    assert _charges(db, tenant) == []
    assert tenant.billing_charged_until == date(2026, 4, 1)

    tenant.plan_code = _plan(db).code
    db.flush()
    cashflow_service.sync_charges(db, today=date(2026, 4, 2))
    assert [c.period_start for c in _charges(db, tenant)] == [date(2026, 4, 1)]


def test_changing_billing_start_replaces_open_charges_but_keeps_paid(db):
    tenant = _priced_tenant(db, start=date(2026, 1, 1))
    cashflow_service.sync_charges(db, today=date(2026, 3, 15))
    first = _charges(db, tenant)[0]
    cashflow_service.update_charge(db, first.id, TenantChargeUpdate(status="paid", paid_on=date(2026, 1, 5)))

    AdminTenantService().update_tenant_subscription(
        db, tenant.id,
        AdminTenantSubscriptionUpdate(plan_code=tenant.plan_code, billing_cycle="monthly", billing_start_date=date(2026, 3, 1)),
        admin_id=None,
    )
    cashflow_service.sync_charges(db, today=date(2026, 3, 15))
    charges = _charges(db, tenant)
    assert [(c.period_start, c.status) for c in charges] == [(date(2026, 1, 1), "paid"), (date(2026, 3, 1), "open")]


def test_charge_status_paid_sets_and_clears_paid_on(db):
    tenant = _priced_tenant(db)
    cashflow_service.sync_charges(db, today=date(2026, 2, 1))
    charge = _charges(db, tenant)[0]
    paid = cashflow_service.update_charge(db, charge.id, TenantChargeUpdate(status="paid"), today=date(2026, 2, 3))
    assert paid.paid_on == date(2026, 2, 3)
    waived = cashflow_service.update_charge(db, charge.id, TenantChargeUpdate(status="waived"))
    assert waived.status == "waived" and waived.paid_on is None


def test_recalculate_uses_current_subscription_and_refuses_paid(db):
    tenant = _priced_tenant(db)
    cashflow_service.sync_charges(db, today=date(2026, 2, 1))
    charge = _charges(db, tenant)[0]
    tenant.discount_percent = 50
    db.flush()
    assert cashflow_service.recalculate_charge(db, charge.id).amount_rp == 1000
    cashflow_service.update_charge(db, charge.id, TenantChargeUpdate(status="paid"))
    with pytest.raises(ValueError):
        cashflow_service.recalculate_charge(db, charge.id)


def test_cost_write_validates_kind_specific_fields():
    with pytest.raises(ValidationError):
        CashflowCostWrite(name="Server", kind="fixed", amount_rp=None, interval="monthly", start_date=date(2026, 1, 1))
    with pytest.raises(ValidationError):
        CashflowCostWrite(name="Gebühr", kind="percent", start_date=date(2026, 1, 1))
    with pytest.raises(ValidationError):
        CashflowCostWrite(name="X", kind="fixed", amount_rp=1, interval="once", start_date=date(2026, 2, 1), end_date=date(2026, 1, 1))
    cleaned = CashflowCostWrite(name="Gebühr", kind="percent", percent_bp=290, amount_rp=5, interval="monthly", start_date=date(2026, 1, 1))
    assert cleaned.amount_rp is None and cleaned.interval is None


def test_cost_occurrences_for_each_interval():
    monthly = CashflowCost(kind="fixed", interval="monthly", amount_rp=100, start_date=date(2025, 11, 30), end_date=date(2026, 3, 1))
    assert cashflow_service.cost_occurrences(monthly, date(2026, 1, 1), date(2026, 12, 31)) == [date(2026, 1, 30), date(2026, 2, 28)]
    yearly = CashflowCost(kind="fixed", interval="yearly", amount_rp=100, start_date=date(2024, 5, 10))
    assert cashflow_service.cost_occurrences(yearly, date(2026, 1, 1), date(2026, 12, 31)) == [date(2026, 5, 10)]
    once = CashflowCost(kind="fixed", interval="once", amount_rp=100, start_date=date(2026, 7, 1))
    assert cashflow_service.cost_occurrences(once, date(2026, 1, 1), date(2026, 6, 30)) == []


def test_overview_counts_only_paid_income_and_separates_planned_costs(db):
    tenant = _priced_tenant(db, start=date(2026, 1, 1))
    cashflow_service.sync_charges(db, today=date(2026, 3, 15))
    january, february, march = _charges(db, tenant)
    cashflow_service.update_charge(db, january.id, TenantChargeUpdate(status="paid", paid_on=date(2026, 1, 10)))
    cashflow_service.update_charge(db, february.id, TenantChargeUpdate(status="waived"))
    db.add_all([
        CashflowCost(name="Server", kind="fixed", interval="monthly", amount_rp=500, start_date=date(2026, 1, 1), status="active"),
        CashflowCost(name="Zahlung", kind="percent", percent_bp=300, start_date=date(2026, 1, 1), status="active"),
        CashflowCost(name="Neuer Server", kind="fixed", interval="monthly", amount_rp=1000, start_date=date(2026, 2, 1), status="planned"),
    ])
    db.flush()

    result = cashflow_service.overview(db, 2026, today=date(2026, 3, 15))
    jan = result.months[0]
    assert (jan.income_rp, jan.fixed_rp, jan.percent_rp, jan.planned_fixed_rp) == (2000, 500, 60, 0)
    assert result.months[1].income_rp == 0 and result.months[1].planned_fixed_rp == 1000
    assert result.months[2].open_rp == 2000
    assert result.months[3].is_future
    # Bis heute: 3 x Server, Gebühr nur auf die Januarzahlung; geplant Feb + Mär.
    ytd = result.year_to_date
    assert (ytd.income_rp, ytd.expenses_rp, ytd.planned_expenses_rp) == (2000, 1560, 2000)
    assert result.run_rate.fixed_rp == 500 and result.run_rate.planned_fixed_rp == 1000


def test_open_charge_becomes_overdue_after_payment_term(db):
    tenant = _priced_tenant(db, start=date(2026, 1, 1))
    cashflow_service.sync_charges(db, today=date(2026, 2, 15))
    page = cashflow_service.list_charges(db, status="overdue", q="Cashflow Verein", year=None, offset=0, limit=50, today=date(2026, 2, 15))
    # Januar fällig am 31.01. -> überfällig; Februar fällig am 03.03. -> noch offen
    assert [c.period_start for c in page.items] == [date(2026, 1, 1)]
    assert page.items[0].is_overdue and page.items[0].due_on == date(2026, 1, 31)
    assert page.totals["overdue"].count == 1 and page.totals["open"].count == 2


def test_tenant_view_lists_own_charges_with_overdue_status_and_without_note(db):
    tenant = _priced_tenant(db, start=date(2026, 1, 1))
    other = _priced_tenant_other(db)
    cashflow_service.sync_charges(db, today=date(2026, 4, 15))
    january, february, march, april = _charges(db, tenant)
    cashflow_service.update_charge(db, january.id, TenantChargeUpdate(status="paid", paid_on=date(2026, 1, 20), note="intern"))
    cashflow_service.update_charge(db, february.id, TenantChargeUpdate(status="waived", note="Kulanz intern"))

    result = cashflow_service.tenant_charges(db, tenant, today=date(2026, 4, 15))
    assert [c.status for c in result.items] == ["open", "overdue", "waived", "paid"]
    assert result.open.count == 2 and result.overdue.amount_rp == 2000
    assert all(c.id != charge.id for c in result.items for charge in _charges(db, other))
    assert "note" not in result.items[0].model_dump()


def _priced_tenant_other(db):
    tenant = make_tenant(db, name="Anderer Verein")
    tenant.plan_code = "cf_basic"
    tenant.billing_start_date = date(2026, 1, 1)
    db.flush()
    return tenant


def test_tenant_charges_route_only_for_admin_of_own_tenant(db):
    from fastapi import HTTPException

    from app.api.routes.tenants import get_tenant_charges
    from tests.factories import make_current_user

    tenant = _priced_tenant(db, start=date(2026, 1, 1))
    other = make_tenant(db, name="Fremder Verein")
    result = get_tenant_charges(tenant.public_id, db=db, user=make_current_user(tenant.id, role="admin"))
    assert result.items
    for user in (make_current_user(tenant.id, role="writer"), make_current_user(other.id, role="admin")):
        with pytest.raises(HTTPException) as exc:
            get_tenant_charges(tenant.public_id, db=db, user=user)
        assert exc.value.status_code == 403
