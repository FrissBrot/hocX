"""Mandanten koennen im Adminportal fuer die oeffentliche Website markiert werden und erscheinen
dort unter "Im Einsatz bei" als Kunden (nur der Name, kein Logo). Standard: nicht gelistet - ein
Verein soll nie ohne bewusste Freigabe oeffentlich genannt werden.

Revision ID: 0104_tenant_show_on_website
Revises: 0103_plan_is_featured
Create Date: 2026-10-10
"""

import sqlalchemy as sa
from alembic import op

revision = "0104_tenant_show_on_website"
down_revision = "0103_plan_is_featured"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenant", sa.Column("show_on_website", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")))


def downgrade() -> None:
    op.drop_column("tenant", "show_on_website")
