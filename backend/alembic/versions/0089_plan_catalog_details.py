"""Preiskatalog fuers neue Admin-Design: Plaene bekommen eine Beschreibung und einen Status
"buchbar" (nicht buchbare Plaene wie 'legacy' erscheinen nicht bei "Neuer Mandant", koennen aber
einzelnen Mandanten zugewiesen werden). Mandanten bekommen einen Rabatt in Prozent und eine
interne Notiz zum Abo.

Revision ID: 0089_plan_catalog_details
Revises: 0088_remove_manual_storage_quota
Create Date: 2026-09-23
"""

import sqlalchemy as sa
from alembic import op

revision = "0089_plan_catalog_details"
down_revision = "0088_remove_manual_storage_quota"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("plan", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("plan", sa.Column("is_bookable", sa.Boolean(), nullable=False, server_default=sa.text("TRUE")))
    op.get_bind().execute(
        sa.text(
            "UPDATE plan SET is_bookable = FALSE, "
            "description = COALESCE(description, 'Übernommen aus dem bisherigen System — ohne Limits bei Nutzern und Speicher.') "
            "WHERE code = 'legacy'"
        )
    )

    op.add_column("tenant", sa.Column("discount_percent", sa.SmallInteger(), nullable=False, server_default=sa.text("0")))
    op.create_check_constraint("ck_tenant_discount_percent", "tenant", "discount_percent BETWEEN 0 AND 100")
    op.add_column("tenant", sa.Column("billing_note", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("tenant", "billing_note")
    op.drop_constraint("ck_tenant_discount_percent", "tenant", type_="check")
    op.drop_column("tenant", "discount_percent")
    op.drop_column("plan", "is_bookable")
    op.drop_column("plan", "description")
