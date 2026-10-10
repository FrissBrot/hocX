"""Oeffentliche Website (Landing Page auf der Hauptdomain) zieht ihre Preiskarten direkt aus dem
Preiskatalog. is_featured markiert den Plan, der dort als "Beliebteste Wahl" hervorgehoben wird -
hoechstens einer, das stellt AdminTenantService.upsert_plan sicher (setzt alle anderen zurueck).
Der bisherige mittlere Seed-Plan 'standard' wird als Startwert markiert.

Revision ID: 0103_plan_is_featured
Revises: 0102_calendar_feed
Create Date: 2026-10-10
"""

import sqlalchemy as sa
from alembic import op

revision = "0103_plan_is_featured"
down_revision = "0102_calendar_feed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("plan", sa.Column("is_featured", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")))
    op.get_bind().execute(sa.text("UPDATE plan SET is_featured = TRUE WHERE code = 'standard'"))


def downgrade() -> None:
    op.drop_column("plan", "is_featured")
