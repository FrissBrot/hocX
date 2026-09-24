"""Speicher-Zusatzpakete: Mandanten koennen zusaetzlich zum Plan-Kontingent feste
Speicherpakete zubuchen (mehrfach, ueber `quantity`). storage_package ist der Preiskatalog
(analog zu plan/feature), tenant_storage_package die Zuweisung pro Mandant.

tenant.storage_quota_manual_override haelt fest, ob ein Admin storage_quota_bytes manuell per
PATCH .../storage-quota gesetzt hat - AdminTenantService.recompute_effective_storage_quota()
(ausgeloest bei Planwechsel und bei jeder Paket-Zuweisungsaenderung) ueberschreibt diesen Wert
dann nicht, sonst wuerde eine individuelle Enterprise-Sondergrenze beim naechsten Planwechsel
stillschweigend verschwinden.

Kein Backfill fuer storage_package/tenant_storage_package - komplett neues Konzept, vor diesem
Umbau gab es keine Zusatzpakete. storage_quota_manual_override startet fuer jeden
Bestandsmandanten auf false (Server-Default), also greift die automatische Neuberechnung ab
sofort ganz normal.

Revision ID: 0087_storage_packages
Revises: 0086_custom_domain_enforcement
Create Date: 2026-09-23
"""

import sqlalchemy as sa
from alembic import op

revision = "0087_storage_packages"
down_revision = "0086_custom_domain_enforcement"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenant",
        sa.Column("storage_quota_manual_override", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")),
    )

    op.create_table(
        "storage_package",
        sa.Column("code", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("bytes", sa.BigInteger(), nullable=False),
        sa.Column("price_monthly_rp", sa.Integer(), nullable=True),
        sa.Column("price_yearly_rp", sa.Integer(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )

    op.create_table(
        "tenant_storage_package",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("package_code", sa.Text(), sa.ForeignKey("storage_package.code", ondelete="CASCADE"), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("added_by_admin_id", sa.BigInteger(), sa.ForeignKey("platform_admin.id", ondelete="SET NULL"), nullable=True),
        sa.UniqueConstraint("tenant_id", "package_code", name="uq_tenant_storage_package_tenant_code"),
    )


def downgrade() -> None:
    op.drop_table("tenant_storage_package")
    op.drop_table("storage_package")
    op.drop_column("tenant", "storage_quota_manual_override")
