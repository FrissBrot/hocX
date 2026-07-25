"""add template.todo_due_event_tag and protocol_todo.closed_in_protocol_id

Revision ID: 0040_missing_legacy_columns
Revises: 0039_system_error_log
Create Date: 2026-07-25

0007_runtime_columns was written to port every ALTER/CREATE from the old
ensure_runtime_columns() into proper Alembic migrations, but missed transcribing
these two specific columns. They've existed on every database that evolved through
that pre-Alembic era (this includes hocx.tweber.ch), which is why this went
unnoticed - only a database that only ever ran `alembic upgrade head` (a fresh
install) is missing them. Confirmed via `alembic.autogenerate.compare_metadata`
against a scratch database migrated from empty: these were the only two genuine
`add_column` diffs between a fresh-migrated schema and what the ORM models expect.

Written idempotently (IF NOT EXISTS / existence checks) rather than with plain
op.add_column/op.create_foreign_key, since - unlike a normal migration - this one
has to apply cleanly to *both* kinds of database: fresh installs where the columns
are genuinely missing, and already-evolved ones (like hocx.tweber.ch) where the
legacy code already created them under a different, unnamed constraint.
"""

from __future__ import annotations

from alembic import op

revision = "0040_missing_legacy_columns"
down_revision = "0039_system_error_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE template ADD COLUMN IF NOT EXISTS todo_due_event_tag TEXT")
    op.execute("ALTER TABLE protocol_todo ADD COLUMN IF NOT EXISTS closed_in_protocol_id BIGINT")
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint c
                JOIN pg_attribute a ON a.attnum = ANY(c.conkey) AND a.attrelid = c.conrelid
                WHERE c.contype = 'f' AND c.conrelid = 'protocol_todo'::regclass AND a.attname = 'closed_in_protocol_id'
            ) THEN
                ALTER TABLE protocol_todo ADD CONSTRAINT fk_protocol_todo_closed_in_protocol
                    FOREIGN KEY (closed_in_protocol_id) REFERENCES protocol(id) ON DELETE SET NULL;
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE protocol_todo DROP CONSTRAINT IF EXISTS fk_protocol_todo_closed_in_protocol")
    op.execute("ALTER TABLE protocol_todo DROP COLUMN IF EXISTS closed_in_protocol_id")
    op.execute("ALTER TABLE template DROP COLUMN IF EXISTS todo_due_event_tag")
