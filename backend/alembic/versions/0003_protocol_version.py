"""add version fields to protocol

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-02
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_protocol_version"
down_revision = "0002_tenant_tag_config"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("protocol", sa.Column("version_major", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("protocol", sa.Column("version_minor", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("protocol", "version_minor")
    op.drop_column("protocol", "version_major")
