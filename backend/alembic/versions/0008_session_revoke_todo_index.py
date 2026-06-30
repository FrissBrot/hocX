"""session_revoke_at for token invalidation + protocol_todo index

Revision ID: 0008_session_revoke_todo_index
Revises: 0007_runtime_columns
Create Date: 2026-05-03
"""
from __future__ import annotations

from alembic import op


revision = "0008_session_revoke_todo_index"
down_revision = "0007_runtime_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # session_revoke_at: when set, tokens issued before this timestamp are invalid
    op.execute("ALTER TABLE app_user ADD COLUMN IF NOT EXISTS session_revoke_at TIMESTAMPTZ")

    # Composite index for the tenant todo list (filters by tenant_id + orders by todo_status_id)
    op.execute("CREATE INDEX IF NOT EXISTS idx_protocol_todo_tenant_status ON protocol_todo (tenant_id, todo_status_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_protocol_todo_tenant_status")
    op.execute("ALTER TABLE app_user DROP COLUMN IF EXISTS session_revoke_at")
