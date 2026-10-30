"""Rabatt eines Mandanten mit Nachkommastellen.

Im Adminportal lässt sich der Rabatt neu auch über den gewünschten Preis setzen; hocX rechnet
daraus die Prozente. Damit der Preis auf den Rappen genau herauskommt, reicht eine ganze Zahl
nicht mehr: ``tenant.discount_percent`` wird ``numeric(7,4)`` (z.B. 12.3457 %). Bestehende
Werte bleiben unverändert, die Prüfung 0–100 aus 0089 gilt weiter.

Revision ID: 0161_tenant_discount_decimal
Revises: 0160_template_catalog_key
Create Date: 2026-10-30
"""

import sqlalchemy as sa
from alembic import op

revision = "0161_tenant_discount_decimal"
down_revision = "0160_template_catalog_key"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "tenant",
        "discount_percent",
        type_=sa.Numeric(7, 4),
        existing_type=sa.SmallInteger(),
        existing_nullable=False,
        existing_server_default=sa.text("0"),
        postgresql_using="discount_percent::numeric(7,4)",
    )


def downgrade() -> None:
    op.alter_column(
        "tenant",
        "discount_percent",
        type_=sa.SmallInteger(),
        existing_type=sa.Numeric(7, 4),
        existing_nullable=False,
        existing_server_default=sa.text("0"),
        postgresql_using="round(discount_percent)::smallint",
    )
