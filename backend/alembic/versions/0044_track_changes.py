"""add track-changes columns to protocol, protocol_text, protocol_todo

Supports the "Änderungen nachverfolgen" (Word-style track changes) feature:
while a protocol is in status 'geplant' and track_changes_enabled is true,
edits to text/todos are marked and, for todos, deletions are deferred
(pending_delete) instead of applied immediately, so they can render
struck-through until the protocol moves to 'durchgeführt' (see
protocol_service.py's _clear_tracked_changes). List tracking needs no new
columns - it lives entirely in the existing configuration_snapshot_json JSONB
(see list_snapshot_service.py).

Revision ID: 0044_track_changes
Revises: 0043_list_content_version
Create Date: 2026-07-31
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0044_track_changes"
down_revision = "0043_list_content_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "protocol",
        sa.Column("track_changes_enabled", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column("protocol_text", sa.Column("tracked_baseline_content", sa.Text(), nullable=True))
    op.add_column(
        "protocol_text",
        sa.Column("tracked_dirty", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column("protocol_todo", sa.Column("tracked_change", sa.Text(), nullable=True))
    op.add_column(
        "protocol_todo",
        sa.Column("tracked_change_before_json", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "protocol_todo",
        sa.Column("pending_delete", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("protocol_todo", "pending_delete")
    op.drop_column("protocol_todo", "tracked_change_before_json")
    op.drop_column("protocol_todo", "tracked_change")
    op.drop_column("protocol_text", "tracked_dirty")
    op.drop_column("protocol_text", "tracked_baseline_content")
    op.drop_column("protocol", "track_changes_enabled")
