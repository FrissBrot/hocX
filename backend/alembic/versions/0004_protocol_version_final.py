"""add version_final_minor to protocol

Revision ID: 0004_protocol_version_final
Revises: 0003_protocol_version
Create Date: 2026-04-02
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_protocol_version_final"
down_revision = "0003_protocol_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("protocol", sa.Column("version_final_minor", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("protocol", "version_final_minor")
