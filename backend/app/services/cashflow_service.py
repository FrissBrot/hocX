"""Cashflow im Plattform-Adminportal (/admin/cashflow).

Zwei Datenquellen:

- Kosten (cashflow_cost): fix mit Betrag je Intervall ab dem Abo-Datum, oder prozentual auf
  jede bezahlte Forderung (Zahlungsgebühren). Nur 'active' wird verrechnet; 'planned' läuft als
  zweite Rechnung «inkl. geplanter Kosten» mit.
- Forderungen (tenant_charge): was ein Mandant je Abrechnungsperiode schuldet. Sie entstehen
  automatisch ab dem Abo-Start des Mandanten (tenant.billing_start_date, sonst Erstellungsdatum)
  bis zur laufenden Periode, Betrag aus Plan + Zusatzmodulen - Rabatt + Speicherpaketen,
  eingefroren beim Entstehen. Nur 'paid' zählt als Einnahme (am Zahlungsdatum); 'open' und
  'waived' (erlassen) fehlen im Cashflow.

Die Erzeugung läuft beim Öffnen der Übersicht bzw. Forderungsliste (sync_charges), nicht als
Hintergrundjob: idempotent über den Cursor tenant.billing_charged_until und die Eindeutigkeit
(tenant_id, period_start), serialisiert über ein Advisory-Lock. Lesende Aufrufe warten nicht auf
das Lock (pg_try_advisory_xact_lock) und laden nur fällige Mandanten samt gesammelter
Preisgrundlage (PricingContext) - im Normalfall kostet der Abgleich so eine Abfrage.
"""

from __future__ import annotations

import calendar
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import and_, delete, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.error_log import record_system_error

from app.models import CashflowCost, Feature, Plan, PlanFeature, StoragePackage, Tenant, TenantCharge, TenantFeature, TenantStoragePackage
from app.schemas.cashflow import (
    CashflowBalance,
    CashflowCostRead,
    CashflowCostWrite,
    CashflowMonth,
    CashflowOverview,
    CashflowRunRate,
    TenantChargePage,
    TenantChargeRead,
    TenantChargeStatusTotals,
    TenantChargeUpdate,
    TenantPortalCharge,
    TenantPortalCharges,
)

_TZ = ZoneInfo("Europe/Zurich")
# Advisory-Lock der Forderungserzeugung (Namensraum 2026000xx, siehe background_loops.py).
SYNC_LOCK_ID = 202600040
# Obergrenze je Mandant und Lauf (50 Jahre monatlich) - schützt vor einem Tippfehler im Abo-Start.
_MAX_PERIODS_PER_SYNC = 600
CHARGE_STATUSES = ("open", "paid", "waived")
# Zahlungsfrist ab Periodenbeginn; danach gilt eine offene Forderung als überfällig.
PAYMENT_TERM_DAYS = 30


def today_local() -> date:
    return datetime.now(_TZ).date()


def add_months(value: date, months: int, anchor_day: int | None = None) -> date:
    """value + months Monate; der Tag folgt anchor_day (bzw. value.day), am Monatsende gekappt -
    ein Abo vom 31. fällt so auf den 28./29. Februar und danach wieder auf den 31. März."""
    total = value.year * 12 + value.month - 1 + months
    year, month = divmod(total, 12)
    month += 1
    day = min(anchor_day or value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def billing_start(tenant: Tenant) -> date:
    if tenant.billing_start_date is not None:
        return tenant.billing_start_date
    return tenant.created_at.astimezone(_TZ).date() if tenant.created_at is not None else today_local()


def _cycle_months(cycle: str) -> int:
    return 12 if cycle == "yearly" else 1


# --------------------------------------------------------------------------- Forderungen


def discounted_rp(subtotal_rp: int, discount_percent: Decimal | float | int) -> int:
    """Betrag nach Rabatt, kaufmännisch auf den Rappen gerundet - dieselbe Rechnung wie
    estimateSubscriptionCost im Adminportal (Math.round)."""
    factor = (Decimal(100) - Decimal(str(discount_percent))) / Decimal(100)
    return int((Decimal(subtotal_rp) * factor).quantize(Decimal(1), rounding=ROUND_HALF_UP))


@dataclass
class PricingContext:
    """Preisgrundlagen gesammelt geladen (Audit 08, 2026-11): früher machte compute_tenant_charge
    rund fünf Abfragen je Mandant, die Laufrate der Übersicht also über 1000 bei 300 Mandanten."""

    plans: dict[str, Plan]
    plan_features: dict[str, set[str]]
    feature_prices: dict[str, tuple[str, int]]
    booked: dict[int, set[str]]
    packages: dict[int, list[tuple[StoragePackage, int]]]

    @classmethod
    def load(cls, db: Session, tenant_ids: list[int] | None = None) -> "PricingContext":
        plan_features: dict[str, set[str]] = {}
        for plan_code, feature_code in db.execute(select(PlanFeature.plan_code, PlanFeature.feature_code)):
            plan_features.setdefault(plan_code, set()).add(feature_code)
        booked_query = select(TenantFeature.tenant_id, TenantFeature.feature_code).where(TenantFeature.access == "full")
        package_query = (
            select(TenantStoragePackage.tenant_id, StoragePackage, TenantStoragePackage.quantity)
            .join(StoragePackage, TenantStoragePackage.package_code == StoragePackage.code)
            .order_by(StoragePackage.sort_order, StoragePackage.name)
        )
        if tenant_ids is not None:
            booked_query = booked_query.where(TenantFeature.tenant_id.in_(tenant_ids))
            package_query = package_query.where(TenantStoragePackage.tenant_id.in_(tenant_ids))
        booked: dict[int, set[str]] = {}
        for tenant_id, feature_code in db.execute(booked_query):
            booked.setdefault(tenant_id, set()).add(feature_code)
        packages: dict[int, list[tuple[StoragePackage, int]]] = {}
        for tenant_id, package, quantity in db.execute(package_query):
            packages.setdefault(tenant_id, []).append((package, quantity))
        return cls(
            plans={plan.code: plan for plan in db.scalars(select(Plan))},
            plan_features=plan_features,
            feature_prices={
                feature.code: (feature.name, feature.standalone_price_monthly_rp)
                for feature in db.scalars(select(Feature).where(Feature.standalone_price_monthly_rp.is_not(None)))
            },
            booked=booked,
            packages=packages,
        )


def compute_tenant_charge(db: Session, tenant: Tenant, context: PricingContext | None = None) -> tuple[int | None, list[dict]]:
    """Betrag einer Periode nach dem aktuellen Abo. Gleiche Regel wie die Kostenvorschau im
    Admin-Tab «Plan & Abo» (Plan + Zusatzmodule, bei jährlicher Abrechnung Monatspreis x 12,
    abzüglich Rabatt), zusätzlich die zugebuchten Speicherpakete (ohne Rabatt).
    None = kein bestimmbarer Preis (kein Plan bzw. Plan ohne Preis und ohne Zusatzmodule).
    Für viele Mandanten einen gemeinsamen PricingContext übergeben."""
    if tenant.plan_code is None:
        return None, []
    if context is None:
        context = PricingContext.load(db, tenant_ids=[tenant.id])
    plan = context.plans.get(tenant.plan_code)
    if plan is None:
        return None, []
    yearly = tenant.billing_cycle == "yearly"
    factor = 12 if yearly else 1
    lines: list[dict] = []

    plan_rp = plan.price_yearly_rp if yearly else plan.price_monthly_rp
    if plan_rp is not None:
        lines.append({"kind": "plan", "label": plan.name, "amount_rp": plan_rp})

    plan_codes = context.plan_features.get(plan.code, set())
    # Nur voll gebuchte Features kosten; nach einem Downgrade (nur lesen) nicht mehr
    add_on_codes = context.booked.get(tenant.id, set()) - plan_codes
    add_ons = sorted(
        (context.feature_prices[code] for code in add_on_codes if code in context.feature_prices), key=lambda item: item[0]
    )
    for name, price in add_ons:
        lines.append({"kind": "feature", "label": name, "amount_rp": price * factor})

    if not lines:
        return None, []
    subtotal = sum(line["amount_rp"] for line in lines)
    if tenant.discount_percent:
        discounted = discounted_rp(subtotal, tenant.discount_percent)
        lines.append({"kind": "discount", "label": "discount", "percent": float(tenant.discount_percent), "amount_rp": discounted - subtotal})

    for package, quantity in context.packages.get(tenant.id, []):
        if yearly:
            price = package.price_yearly_rp if package.price_yearly_rp is not None else (
                package.price_monthly_rp * 12 if package.price_monthly_rp is not None else None
            )
        else:
            price = package.price_monthly_rp
        if price is None:
            continue
        lines.append({"kind": "storage_package", "label": package.name, "quantity": quantity, "amount_rp": price * quantity})

    return sum(line["amount_rp"] for line in lines), lines


def sync_charges(db: Session, *, today: date | None = None, tenant_ids: list[int] | None = None, wait: bool = True) -> int:
    """Legt für jeden Mandanten die fehlenden Forderungen bis zur laufenden Periode an und
    committet. Gibt die Anzahl neuer Forderungen zurück. Perioden ohne bestimmbaren Preis
    (oder mit 0) werden übersprungen, der Cursor rückt trotzdem vor - eine spätere
    Preisänderung erzeugt so nie rückwirkend Forderungen."""
    today = today or today_local()
    if not wait:
        # Lesende Aufrufe warten nicht auf einen laufenden Abgleich (Audit 08, 2026-11): der
        # Lock war global und blockierend, Mandanten-Admins hingen sonst an der Admin-Übersicht.
        if not db.scalar(text("SELECT pg_try_advisory_xact_lock(:id)"), {"id": SYNC_LOCK_ID}):
            return 0
    else:
        db.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": SYNC_LOCK_ID})
    created = 0
    # Nur Mandanten mit fälliger Periode laden - im Normalfall keiner, dann bleibt es bei einer Abfrage.
    query = (
        select(Tenant)
        .where((Tenant.billing_charged_until.is_(None)) | (Tenant.billing_charged_until <= today))
        .order_by(Tenant.id)
    )
    if tenant_ids is not None:
        query = query.where(Tenant.id.in_(tenant_ids))
    due = db.scalars(query).all()
    context = PricingContext.load(db, tenant_ids=[tenant.id for tenant in due]) if due else None
    for tenant in due:
        start = billing_start(tenant)
        cursor = tenant.billing_charged_until or start
        if cursor > today:
            continue
        amount, lines = compute_tenant_charge(db, tenant, context)
        months = _cycle_months(tenant.billing_cycle)
        periods = 0
        while cursor <= today and periods < _MAX_PERIODS_PER_SYNC:
            end = add_months(cursor, months, anchor_day=start.day)
            if amount:
                result = db.execute(
                    pg_insert(TenantCharge)
                    .values(
                        tenant_id=tenant.id,
                        tenant_name=tenant.name,
                        period_start=cursor,
                        period_end=end,
                        billing_cycle=tenant.billing_cycle,
                        amount_rp=amount,
                        lines=lines,
                    )
                    .on_conflict_do_nothing(constraint="uq_tenant_charge_period")
                )
                created += result.rowcount or 0
            cursor = end
            periods += 1
        tenant.billing_charged_until = cursor
    db.commit()
    return created


def reset_open_charges(db: Session, tenant: Tenant) -> None:
    """Nach einer Änderung des Abo-Starts: offene Forderungen verwerfen und den Cursor neu
    setzen - bezahlte und erlassene bleiben. Committet nicht."""
    db.execute(delete(TenantCharge).where(TenantCharge.tenant_id == tenant.id, TenantCharge.status == "open"))
    last_end = db.scalar(select(func.max(TenantCharge.period_end)).where(TenantCharge.tenant_id == tenant.id))
    start = billing_start(tenant)
    tenant.billing_charged_until = max(start, last_end) if last_end is not None else None


def due_on(period_start: date) -> date:
    return period_start + timedelta(days=PAYMENT_TERM_DAYS)


def _overdue_filter(today: date):
    """Offen und Zahlungsfrist abgelaufen (Fälligkeit vor heute)."""
    return and_(TenantCharge.status == "open", TenantCharge.period_start < today - timedelta(days=PAYMENT_TERM_DAYS))


def _charge_read(charge: TenantCharge, tenant_public_id: uuid.UUID | None, today: date | None = None) -> TenantChargeRead:
    today = today or today_local()
    due = due_on(charge.period_start)
    return TenantChargeRead(
        due_on=due,
        is_overdue=charge.status == "open" and due < today,
        id=charge.id,
        tenant_id=tenant_public_id,
        tenant_name=charge.tenant_name,
        period_start=charge.period_start,
        period_end=charge.period_end,
        billing_cycle=charge.billing_cycle,
        amount_rp=charge.amount_rp,
        lines=charge.lines or [],
        status=charge.status,
        paid_on=charge.paid_on,
        note=charge.note,
        updated_at=charge.updated_at,
    )


def list_charges(
    db: Session, *, status: str | None, q: str | None, year: int | None, offset: int, limit: int, today: date | None = None
) -> TenantChargePage:
    today = today or today_local()
    base = select(TenantCharge, Tenant.public_id).outerjoin(Tenant, Tenant.id == TenantCharge.tenant_id)
    filters = []
    if q and q.strip():
        filters.append(TenantCharge.tenant_name.ilike(f"%{q.strip()}%"))
    if year is not None:
        filters.append(TenantCharge.period_start.between(date(year, 1, 1), date(year, 12, 31)))
    totals = {key: TenantChargeStatusTotals() for key in CHARGE_STATUSES}
    for row_status, count, amount in db.execute(
        select(TenantCharge.status, func.count(), func.coalesce(func.sum(TenantCharge.amount_rp), 0)).where(*filters).group_by(TenantCharge.status)
    ):
        totals[row_status] = TenantChargeStatusTotals(count=int(count), amount_rp=int(amount))
    overdue_count, overdue_amount = db.execute(
        select(func.count(), func.coalesce(func.sum(TenantCharge.amount_rp), 0)).where(*filters, _overdue_filter(today))
    ).one()
    totals["overdue"] = TenantChargeStatusTotals(count=int(overdue_count), amount_rp=int(overdue_amount))
    if status == "overdue":
        filters.append(_overdue_filter(today))
    elif status is not None:
        filters.append(TenantCharge.status == status)
    total = int(db.scalar(select(func.count()).select_from(TenantCharge).where(*filters)) or 0)
    rows = db.execute(
        base.where(*filters).order_by(TenantCharge.period_start.desc(), TenantCharge.tenant_name).offset(offset).limit(limit)
    ).all()
    return TenantChargePage(items=[_charge_read(charge, public_id, today) for charge, public_id in rows], total=total, totals=totals)


def tenant_charges(db: Session, tenant: Tenant, *, today: date | None = None) -> TenantPortalCharges:
    """Forderungen aus Sicht des Mandanten (Abo & Nutzung): ohne interne Notiz."""
    today = today or today_local()
    try:
        sync_charges(db, today=today, tenant_ids=[tenant.id], wait=False)
    except SQLAlchemyError as exc:
        # Ein lesender Aufruf darf am Abgleich nicht scheitern (z. B. Schreibsperre während einer
        # Wartung) - dann eben die bisherigen Forderungen zeigen und den Fehler protokollieren.
        db.rollback()
        record_system_error(db, exc=exc, tenant_id=tenant.id)
    charges = db.scalars(
        select(TenantCharge).where(TenantCharge.tenant_id == tenant.id).order_by(TenantCharge.period_start.desc())
    ).all()
    items = []
    for charge in charges:
        read = _charge_read(charge, tenant.public_id, today)
        items.append(
            TenantPortalCharge(
                id=read.id, period_start=read.period_start, period_end=read.period_end, billing_cycle=read.billing_cycle,
                amount_rp=read.amount_rp, lines=read.lines, status="overdue" if read.is_overdue else read.status,
                due_on=read.due_on, paid_on=read.paid_on,
            )
        )
    open_items = [item for item in items if item.status in ("open", "overdue")]
    overdue_items = [item for item in items if item.status == "overdue"]
    return TenantPortalCharges(
        items=items,
        open=TenantChargeStatusTotals(count=len(open_items), amount_rp=sum(item.amount_rp for item in open_items)),
        overdue=TenantChargeStatusTotals(count=len(overdue_items), amount_rp=sum(item.amount_rp for item in overdue_items)),
        payment_term_days=PAYMENT_TERM_DAYS,
    )


def _charge_with_tenant(db: Session, charge_id: uuid.UUID) -> tuple[TenantCharge, Tenant | None] | None:
    charge = db.get(TenantCharge, charge_id)
    if charge is None:
        return None
    return charge, (db.get(Tenant, charge.tenant_id) if charge.tenant_id is not None else None)


def update_charge(db: Session, charge_id: uuid.UUID, payload: TenantChargeUpdate, *, today: date | None = None) -> TenantChargeRead | None:
    found = _charge_with_tenant(db, charge_id)
    if found is None:
        return None
    charge, tenant = found
    charge.status = payload.status
    charge.paid_on = (payload.paid_on or today or today_local()) if payload.status == "paid" else None
    if "note" in payload.model_fields_set:
        charge.note = (payload.note or "").strip() or None
    charge.updated_at = datetime.now(timezone.utc)
    db.commit()
    return _charge_read(charge, tenant.public_id if tenant else None)


def recalculate_charge(db: Session, charge_id: uuid.UUID) -> TenantChargeRead | None:
    """Betrag einer nicht bezahlten Forderung nach dem aktuellen Abo neu berechnen (z. B. nach
    einem Planwechsel mitten in der Periode)."""
    found = _charge_with_tenant(db, charge_id)
    if found is None:
        return None
    charge, tenant = found
    if charge.status == "paid":
        raise ValueError("Bezahlte Forderungen bleiben unverändert")
    if tenant is None:
        raise ValueError("Der Mandant existiert nicht mehr")
    amount, lines = compute_tenant_charge(db, tenant)
    if not amount:
        raise ValueError("Für das aktuelle Abo ist kein Preis bestimmbar")
    charge.amount_rp = amount
    charge.lines = lines
    charge.tenant_name = tenant.name
    charge.updated_at = datetime.now(timezone.utc)
    db.commit()
    return _charge_read(charge, tenant.public_id)


# --------------------------------------------------------------------------- Kosten


def cost_occurrences(cost: CashflowCost, start: date, end: date) -> list[date]:
    """Fälligkeiten einer fixen Ausgabe im Bereich [start, end]."""
    if cost.kind != "fixed" or end < start:
        return []
    last = min(end, cost.end_date) if cost.end_date is not None else end
    if cost.interval == "once":
        return [cost.start_date] if start <= cost.start_date <= last else []
    step = _cycle_months(cost.interval)
    months_until_start = (start.year - cost.start_date.year) * 12 + start.month - cost.start_date.month
    index = max(0, months_until_start // step - 1)
    result: list[date] = []
    while True:
        due = add_months(cost.start_date, index * step)
        if due > last:
            break
        if due >= start:
            result.append(due)
        index += 1
    return result


def _cost_monthly_equivalent(cost: CashflowCost) -> int:
    if cost.kind != "fixed" or cost.amount_rp is None or cost.interval == "once":
        return 0
    return cost.amount_rp if cost.interval == "monthly" else round(cost.amount_rp / 12)


def _percent_applies(cost: CashflowCost, on: date) -> bool:
    return cost.start_date <= on and (cost.end_date is None or on <= cost.end_date)


def cost_read(cost: CashflowCost, *, today: date | None = None) -> CashflowCostRead:
    today = today or today_local()
    upcoming = cost_occurrences(cost, today, add_months(today, 13)) if cost.kind == "fixed" else []
    data = CashflowCostRead.model_validate(cost)
    data.next_due_on = upcoming[0] if upcoming else None
    data.monthly_equivalent_rp = _cost_monthly_equivalent(cost)
    return data


def list_costs(db: Session) -> list[CashflowCostRead]:
    costs = db.scalars(select(CashflowCost).order_by(CashflowCost.status, CashflowCost.kind, CashflowCost.name)).all()
    today = today_local()
    return [cost_read(cost, today=today) for cost in costs]


def _apply_cost(cost: CashflowCost, payload: CashflowCostWrite) -> None:
    cost.name = payload.name.strip()
    cost.kind = payload.kind
    cost.amount_rp = payload.amount_rp
    cost.percent_bp = payload.percent_bp
    cost.interval = payload.interval
    cost.start_date = payload.start_date
    cost.end_date = payload.end_date
    cost.status = payload.status
    cost.note = (payload.note or "").strip() or None
    cost.updated_at = datetime.now(timezone.utc)


def create_cost(db: Session, payload: CashflowCostWrite) -> CashflowCostRead:
    if not payload.name.strip():
        raise ValueError("Name fehlt")
    cost = CashflowCost()
    _apply_cost(cost, payload)
    db.add(cost)
    db.commit()
    db.refresh(cost)
    return cost_read(cost)


def update_cost(db: Session, cost_id: uuid.UUID, payload: CashflowCostWrite) -> CashflowCostRead | None:
    cost = db.get(CashflowCost, cost_id)
    if cost is None:
        return None
    if not payload.name.strip():
        raise ValueError("Name fehlt")
    _apply_cost(cost, payload)
    db.commit()
    db.refresh(cost)
    return cost_read(cost)


def set_cost_status(db: Session, cost_id: uuid.UUID, status: str) -> CashflowCostRead | None:
    cost = db.get(CashflowCost, cost_id)
    if cost is None:
        return None
    cost.status = status
    cost.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(cost)
    return cost_read(cost)


def delete_cost(db: Session, cost_id: uuid.UUID) -> bool:
    cost = db.get(CashflowCost, cost_id)
    if cost is None:
        return False
    db.delete(cost)
    db.commit()
    return True


# --------------------------------------------------------------------------- Übersicht


@dataclass
class _Expenses:
    fixed: int = 0
    percent: int = 0
    planned_fixed: int = 0
    planned_percent: int = 0


def _expenses(costs: list[CashflowCost], payments: list[tuple[date, int]], start: date, end: date) -> _Expenses:
    """Ausgaben im Bereich [start, end]: fixe Fälligkeiten und Prozentanteile der darin
    bezahlten Forderungen (je Zahlung gerundet), getrennt nach aktiv und geplant."""
    result = _Expenses()
    in_range = [(paid_on, amount) for paid_on, amount in payments if start <= paid_on <= end]
    for cost in costs:
        planned = cost.status == "planned"
        if cost.kind == "fixed":
            value = len(cost_occurrences(cost, start, end)) * (cost.amount_rp or 0)
            if planned:
                result.planned_fixed += value
            else:
                result.fixed += value
        else:
            value = sum(round(amount * (cost.percent_bp or 0) / 10000) for paid_on, amount in in_range if _percent_applies(cost, paid_on))
            if planned:
                result.planned_percent += value
            else:
                result.percent += value
    return result


def _balance(costs: list[CashflowCost], payments: list[tuple[date, int]], start: date, end: date) -> CashflowBalance:
    if end < start:
        return CashflowBalance()
    expenses = _expenses(costs, payments, start, end)
    return CashflowBalance(
        income_rp=sum(amount for paid_on, amount in payments if start <= paid_on <= end),
        expenses_rp=expenses.fixed + expenses.percent,
        planned_expenses_rp=expenses.planned_fixed + expenses.planned_percent,
    )


def overview(db: Session, year: int | None = None, *, today: date | None = None) -> CashflowOverview:
    today = today or today_local()
    year = year or today.year
    costs = list(db.scalars(select(CashflowCost)).all())
    payments = [
        (paid_on, int(amount))
        for paid_on, amount in db.execute(select(TenantCharge.paid_on, TenantCharge.amount_rp).where(TenantCharge.status == "paid"))
    ]
    open_by_month: dict[str, int] = {}
    for period_start, amount in db.execute(
        select(TenantCharge.period_start, TenantCharge.amount_rp).where(
            TenantCharge.status == "open", TenantCharge.period_start.between(date(year, 1, 1), date(year, 12, 31))
        )
    ):
        key = period_start.strftime("%Y-%m")
        open_by_month[key] = open_by_month.get(key, 0) + int(amount)

    months: list[CashflowMonth] = []
    for month in range(1, 13):
        start, end = date(year, month, 1), _month_end(year, month)
        expenses = _expenses(costs, payments, start, end)
        key = start.strftime("%Y-%m")
        months.append(
            CashflowMonth(
                month=key,
                income_rp=sum(amount for paid_on, amount in payments if start <= paid_on <= end),
                fixed_rp=expenses.fixed,
                percent_rp=expenses.percent,
                planned_fixed_rp=expenses.planned_fixed,
                planned_percent_rp=expenses.planned_percent,
                open_rp=open_by_month.get(key, 0),
                is_future=start > today,
            )
        )

    earliest_candidates = [paid_on for paid_on, _ in payments] + [cost.start_date for cost in costs]
    earliest = min(earliest_candidates) if earliest_candidates else today
    charge_years = db.execute(select(func.min(TenantCharge.period_start), func.max(TenantCharge.period_start))).one()
    first_year = min([earliest.year, today.year] + ([charge_years[0].year] if charge_years[0] else []))
    last_year = max(today.year + 1, year)

    # Laufrate: aktuelle Abos aller Mandanten auf einen Monat umgerechnet, laufende Kosten
    # (Prozentanteile auf diese Monatseinnahmen, daher erst nach der Mandantenschleife).
    run_rate = CashflowRunRate()
    pricing = PricingContext.load(db)
    for tenant in db.scalars(select(Tenant)).all():
        amount, _ = compute_tenant_charge(db, tenant, pricing)
        if amount:
            run_rate.income_rp += round(amount / _cycle_months(tenant.billing_cycle))
            run_rate.paying_tenants += 1
    for cost in costs:
        if cost.end_date is not None and cost.end_date < today:
            continue
        planned = cost.status == "planned"
        if cost.kind == "fixed":
            value = _cost_monthly_equivalent(cost)
            if planned:
                run_rate.planned_fixed_rp += value
            else:
                run_rate.fixed_rp += value
        else:
            value = round(run_rate.income_rp * (cost.percent_bp or 0) / 10000)
            if planned:
                run_rate.planned_percent_rp += value
            else:
                run_rate.percent_rp += value

    status_totals = {key: TenantChargeStatusTotals() for key in CHARGE_STATUSES}
    for row_status, count, amount in db.execute(
        select(TenantCharge.status, func.count(), func.coalesce(func.sum(TenantCharge.amount_rp), 0)).group_by(TenantCharge.status)
    ):
        status_totals[row_status] = TenantChargeStatusTotals(count=int(count), amount_rp=int(amount))
    overdue_count, overdue_amount = db.execute(
        select(func.count(), func.coalesce(func.sum(TenantCharge.amount_rp), 0)).where(_overdue_filter(today))
    ).one()

    return CashflowOverview(
        year=year,
        years=list(range(first_year, last_year + 1)),
        today=today,
        months=months,
        year_to_date=_balance(costs, payments, date(year, 1, 1), min(date(year, 12, 31), today)),
        all_time=_balance(costs, payments, earliest, today),
        run_rate=run_rate,
        open=status_totals["open"],
        waived=status_totals["waived"],
        overdue=TenantChargeStatusTotals(count=int(overdue_count), amount_rp=int(overdue_amount)),
    )

