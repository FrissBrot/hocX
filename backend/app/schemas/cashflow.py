"""Schemas des Cashflows im Plattform-Adminportal (/admin/cashflow). Beträge immer in Rappen."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CostKind = Literal["fixed", "percent"]
CostStatus = Literal["active", "planned"]
CostInterval = Literal["monthly", "yearly", "once"]
ChargeStatus = Literal["open", "paid", "waived"]


class CashflowCostRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    kind: CostKind
    amount_rp: int | None = None
    percent_bp: int | None = None
    interval: CostInterval | None = None
    start_date: date
    end_date: date | None = None
    status: CostStatus
    note: str | None = None
    # Nächste Fälligkeit ab heute (nur fix, None = keine mehr).
    next_due_on: date | None = None
    # Auf einen Monat umgerechnet (monatlich 1:1, jährlich / 12, einmalig 0).
    monthly_equivalent_rp: int = 0
    created_at: datetime
    updated_at: datetime


class CashflowCostWrite(BaseModel):
    # Full-Replace, auch fürs Anlegen.
    name: str = Field(min_length=1, max_length=200)
    kind: CostKind
    amount_rp: int | None = Field(default=None, ge=0)
    # 0.01 % bis 100 %.
    percent_bp: int | None = Field(default=None, ge=1, le=10000)
    interval: CostInterval | None = None
    start_date: date
    end_date: date | None = None
    status: CostStatus = "active"
    note: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _check_kind(self) -> "CashflowCostWrite":
        if self.kind == "fixed":
            if self.amount_rp is None or self.interval is None:
                raise ValueError("Fixe Ausgaben brauchen Betrag und Intervall")
            self.percent_bp = None
        else:
            if self.percent_bp is None:
                raise ValueError("Prozentuale Ausgaben brauchen einen Prozentsatz")
            self.amount_rp = None
            self.interval = None
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("Das Enddatum liegt vor dem Abo-Datum")
        return self


class CashflowCostStatusUpdate(BaseModel):
    status: CostStatus


class TenantChargeLine(BaseModel):
    kind: Literal["plan", "feature", "storage_package", "discount"]
    label: str
    amount_rp: int
    quantity: int | None = None
    percent: int | None = None


class TenantChargeRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID | None = None
    tenant_name: str
    period_start: date
    period_end: date
    billing_cycle: Literal["monthly", "yearly"]
    amount_rp: int
    lines: list[TenantChargeLine] = []
    status: ChargeStatus
    paid_on: date | None = None
    note: str | None = None
    updated_at: datetime
    # Periodenbeginn + Zahlungsfrist; überfällig = offen und Fälligkeit vor heute.
    due_on: date
    is_overdue: bool = False


class TenantChargeStatusTotals(BaseModel):
    count: int = 0
    amount_rp: int = 0


class TenantChargePage(BaseModel):
    items: list[TenantChargeRead]
    total: int
    # Summen je Status über alle Forderungen, die zur Suche passen (unabhängig vom Statusfilter).
    totals: dict[Literal["open", "paid", "waived", "overdue"], TenantChargeStatusTotals]


class TenantChargeUpdate(BaseModel):
    status: ChargeStatus
    # Nur bei 'paid'. Leer = heute.
    paid_on: date | None = None
    note: str | None = Field(default=None, max_length=2000)


class CashflowMonth(BaseModel):
    month: str  # JJJJ-MM
    income_rp: int = 0
    fixed_rp: int = 0
    percent_rp: int = 0
    planned_fixed_rp: int = 0
    planned_percent_rp: int = 0
    # Offene Forderungen mit Periodenbeginn in diesem Monat.
    open_rp: int = 0
    is_future: bool = False


class CashflowBalance(BaseModel):
    income_rp: int = 0
    expenses_rp: int = 0
    # Zusätzlich, wenn die geplanten Kosten schon aktiv wären.
    planned_expenses_rp: int = 0


class CashflowRunRate(BaseModel):
    """Laufender Monat hochgerechnet aus den aktuellen Abos und Kosten."""

    income_rp: int = 0
    fixed_rp: int = 0
    percent_rp: int = 0
    planned_fixed_rp: int = 0
    planned_percent_rp: int = 0
    paying_tenants: int = 0


class CashflowOverview(BaseModel):
    year: int
    years: list[int]
    today: date
    months: list[CashflowMonth]
    # Bis heute im gewählten Jahr bzw. seit Beginn.
    year_to_date: CashflowBalance
    all_time: CashflowBalance
    run_rate: CashflowRunRate
    open: TenantChargeStatusTotals
    waived: TenantChargeStatusTotals
    overdue: TenantChargeStatusTotals


class TenantPortalCharge(BaseModel):
    """Forderung aus Sicht des Mandanten - ohne interne Notiz des Betreibers."""

    id: uuid.UUID
    period_start: date
    period_end: date
    billing_cycle: Literal["monthly", "yearly"]
    amount_rp: int
    lines: list[TenantChargeLine] = []
    status: Literal["open", "overdue", "paid", "waived"]
    due_on: date
    paid_on: date | None = None


class TenantPortalCharges(BaseModel):
    items: list[TenantPortalCharge]
    open: TenantChargeStatusTotals
    overdue: TenantChargeStatusTotals
    payment_term_days: int
