"""Cashflow im Plattform-Adminportal

- cashflow_cost: Ausgaben der Plattform, fix (Betrag je Intervall monatlich/jährlich/einmalig
  ab dem Abo-Datum) oder prozentual (Anteil jeder bezahlten Forderung). Status 'active' wird
  verrechnet, 'planned' nur in der Planrechnung gezeigt.
- tenant_charge: was ein Mandant je Abrechnungsperiode schuldet (keine echte Rechnung).
  Betrag und Aufschlüsselung eingefroren, Status offen/bezahlt/erlassen. tenant_id SET NULL,
  damit die Historie das Löschen eines Mandanten überlebt.
- tenant.billing_start_date (Abo-Start, NULL = Erstellungsdatum) und
  tenant.billing_charged_until (Cursor der Forderungserzeugung).

Revision ID: 0127_cashflow
Revises: 0126_verify_domain
Create Date: 2026-10-17
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0127_cashflow"
down_revision = "0126_verify_domain"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenant", sa.Column("billing_start_date", sa.Date(), nullable=True))
    op.add_column("tenant", sa.Column("billing_charged_until", sa.Date(), nullable=True))

    op.create_table(
        "cashflow_cost",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("amount_rp", sa.Integer(), nullable=True),
        sa.Column("percent_bp", sa.Integer(), nullable=True),
        sa.Column("interval", sa.Text(), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'active'")),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint("kind IN ('fixed', 'percent')", name="ck_cashflow_cost_kind"),
        sa.CheckConstraint("status IN ('active', 'planned')", name="ck_cashflow_cost_status"),
        sa.CheckConstraint("interval IS NULL OR interval IN ('monthly', 'yearly', 'once')", name="ck_cashflow_cost_interval"),
        sa.CheckConstraint(
            "(kind = 'fixed' AND amount_rp IS NOT NULL AND interval IS NOT NULL) OR (kind = 'percent' AND percent_bp IS NOT NULL)",
            name="ck_cashflow_cost_values",
        ),
        sa.CheckConstraint("end_date IS NULL OR end_date >= start_date", name="ck_cashflow_cost_dates"),
    )

    op.create_table(
        "tenant_charge",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenant.id", ondelete="SET NULL"), nullable=True),
        sa.Column("tenant_name", sa.Text(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("billing_cycle", sa.Text(), nullable=False),
        sa.Column("amount_rp", sa.Integer(), nullable=False),
        sa.Column("lines", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'open'")),
        sa.Column("paid_on", sa.Date(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint("status IN ('open', 'paid', 'waived')", name="ck_tenant_charge_status"),
        sa.CheckConstraint("(status = 'paid') = (paid_on IS NOT NULL)", name="ck_tenant_charge_paid_on"),
        sa.CheckConstraint("billing_cycle IN ('monthly', 'yearly')", name="ck_tenant_charge_cycle"),
        sa.UniqueConstraint("tenant_id", "period_start", name="uq_tenant_charge_period"),
    )
    op.create_index("idx_tenant_charge_status", "tenant_charge", ["status", "period_start"])
    op.create_index("idx_tenant_charge_paid_on", "tenant_charge", ["paid_on"], postgresql_where=sa.text("paid_on IS NOT NULL"))


def downgrade() -> None:
    op.drop_table("tenant_charge")
    op.drop_table("cashflow_cost")
    op.drop_column("tenant", "billing_charged_until")
    op.drop_column("tenant", "billing_start_date")
