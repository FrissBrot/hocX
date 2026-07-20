"""add is_cancelled flag to event

Revision ID: 0036_event_is_cancelled
Revises: 0035_abgabebox_log_id_grant
Create Date: 2026-07-20
"""

import sqlalchemy as sa
from alembic import op

revision = "0036_event_is_cancelled"
down_revision = "0035_abgabebox_log_id_grant"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "event",
        sa.Column("is_cancelled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("event", "is_cancelled")
