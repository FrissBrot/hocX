"""ORM-Modelle des Cashflows im Plattform-Adminportal (Migration 0127_cashflow).

Reine Übersicht für den Betreiber: Kosten der Plattform und was Mandanten schulden. Es werden
keine echten Rechnungen erstellt oder versendet.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CashflowCost(Base):
    """Eine Ausgabe der Plattform: fix (Betrag je Intervall ab dem Abo-Datum) oder prozentual
    (Anteil jeder bezahlten Forderung, z. B. Zahlungsgebühren). Nur 'active' wird verrechnet,
    'planned' erscheint nur in der Planrechnung."""

    __tablename__ = "cashflow_cost"
    __table_args__ = (
        CheckConstraint("kind IN ('fixed', 'percent')", name="ck_cashflow_cost_kind"),
        CheckConstraint("status IN ('active', 'planned')", name="ck_cashflow_cost_status"),
        CheckConstraint("interval IS NULL OR interval IN ('monthly', 'yearly', 'once')", name="ck_cashflow_cost_interval"),
        CheckConstraint(
            "(kind = 'fixed' AND amount_rp IS NOT NULL AND interval IS NOT NULL) OR (kind = 'percent' AND percent_bp IS NOT NULL)",
            name="ck_cashflow_cost_values",
        ),
        CheckConstraint("end_date IS NULL OR end_date >= start_date", name="ck_cashflow_cost_dates"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    # Rappen je Intervall (nur kind = 'fixed').
    amount_rp: Mapped[int | None] = mapped_column(Integer)
    # Hundertstel-Prozent (290 = 2.90 %), nur kind = 'percent'.
    percent_bp: Mapped[int | None] = mapped_column(Integer)
    interval: Mapped[str | None] = mapped_column(Text)
    # Abo-Datum: erste Fälligkeit (fix) bzw. ab wann die Gebühr gilt (prozentual).
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))


class TenantCharge(Base):
    """Was ein Mandant für eine Abrechnungsperiode schuldet. Betrag und Aufschlüsselung werden
    beim Entstehen eingefroren; nur 'paid' zählt im Cashflow als Einnahme. Der Mandantenname
    bleibt erhalten, falls der Mandant gelöscht wird (tenant_id wird dann NULL)."""

    __tablename__ = "tenant_charge"
    __table_args__ = (
        CheckConstraint("status IN ('open', 'paid', 'waived')", name="ck_tenant_charge_status"),
        CheckConstraint("(status = 'paid') = (paid_on IS NOT NULL)", name="ck_tenant_charge_paid_on"),
        CheckConstraint("billing_cycle IN ('monthly', 'yearly')", name="ck_tenant_charge_cycle"),
        UniqueConstraint("tenant_id", "period_start", name="uq_tenant_charge_period"),
        Index("idx_tenant_charge_status", "status", "period_start"),
        Index("idx_tenant_charge_paid_on", "paid_on", postgresql_where=text("paid_on IS NOT NULL")),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("tenant.id", ondelete="SET NULL"))
    tenant_name: Mapped[str] = mapped_column(Text, nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    billing_cycle: Mapped[str] = mapped_column(Text, nullable=False)
    amount_rp: Mapped[int] = mapped_column(Integer, nullable=False)
    # [{"kind": "plan"|"feature"|"storage_package"|"discount", "label": ..., "amount_rp": ..., ...}]
    lines: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'open'"))
    paid_on: Mapped[date | None] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
