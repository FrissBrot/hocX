"""add content_version to list_definition

Bumped on any entry create/update/delete or column title/type change, used by
the new list-snapshot-in-protocols feature to cheaply detect "has this list
changed since my snapshot was taken" (see list_snapshot_service.py).

Revision ID: 0043_list_content_version
Revises: 0042_protocol_live_responsible
Create Date: 2026-07-30
"""

import sqlalchemy as sa
from alembic import op

revision = "0043_list_content_version"
down_revision = "0042_protocol_live_responsible"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "list_definition",
        sa.Column("content_version", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("list_definition", "content_version")
