"""missing indexes and check constraints from DB audit

Revision ID: 0009_indexes_and_constraints
Revises: 0008_session_revoke_todo_index
Create Date: 2026-05-03
"""
from __future__ import annotations

from alembic import op


revision = "0009_indexes_and_constraints"
down_revision = "0008_session_revoke_todo_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Missing indexes ────────────────────────────────────────────────────────

    # template: common filter is (tenant_id, status)
    op.execute("CREATE INDEX IF NOT EXISTS idx_template_tenant_status ON template (tenant_id, status)")

    # template_participant: reverse lookup participant → templates
    op.execute("CREATE INDEX IF NOT EXISTS idx_template_participant_participant ON template_participant (participant_id, template_id)")

    # finance_transaction: join from protocol side
    op.execute("CREATE INDEX IF NOT EXISTS idx_finance_transaction_protocol ON finance_transaction (protocol_id) WHERE protocol_id IS NOT NULL")

    # protocol_todo: block-level status filter (block view + exports)
    op.execute("CREATE INDEX IF NOT EXISTS idx_protocol_todo_block_status ON protocol_todo (protocol_element_block_id, todo_status_id) WHERE protocol_element_block_id IS NOT NULL")

    # finance_account: alphabetical list per tenant
    op.execute("CREATE INDEX IF NOT EXISTS idx_finance_account_tenant_name ON finance_account (tenant_id, name)")

    # ── CHECK constraints (NOT VALID: enforced for new writes, skips history) ──

    # At most one due-date field may be set on a todo
    op.execute("""
        ALTER TABLE protocol_todo ADD CONSTRAINT ck_protocol_todo_due_exclusive
        CHECK (
            (due_date IS NOT NULL)::int +
            (due_event_id IS NOT NULL)::int +
            (due_marker IS NOT NULL)::int <= 1
        ) NOT VALID
    """)

    # Fine amounts must be positive
    op.execute("""
        ALTER TABLE attendance_fine ADD CONSTRAINT ck_attendance_fine_amount_positive
        CHECK (amount > 0) NOT VALID
    """)

    # Event participant count cannot be negative
    op.execute("""
        ALTER TABLE event ADD CONSTRAINT ck_event_participant_count_nonneg
        CHECK (participant_count >= 0) NOT VALID
    """)

    # sort_index >= 0 on all tables that carry one
    for table in (
        "protocol_todo",
        "protocol_image",
        "list_entry",
        "template_element",
        "template_element_block",
        "protocol_element",
        "protocol_element_block",
    ):
        op.execute(f"""
            ALTER TABLE {table} ADD CONSTRAINT ck_{table}_sort_nonneg
            CHECK (sort_index >= 0) NOT VALID
        """)


def downgrade() -> None:
    for table in (
        "protocol_todo",
        "protocol_image",
        "list_entry",
        "template_element",
        "template_element_block",
        "protocol_element",
        "protocol_element_block",
    ):
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS ck_{table}_sort_nonneg")

    op.execute("ALTER TABLE event DROP CONSTRAINT IF EXISTS ck_event_participant_count_nonneg")
    op.execute("ALTER TABLE attendance_fine DROP CONSTRAINT IF EXISTS ck_attendance_fine_amount_positive")
    op.execute("ALTER TABLE protocol_todo DROP CONSTRAINT IF EXISTS ck_protocol_todo_due_exclusive")

    op.execute("DROP INDEX IF EXISTS idx_finance_account_tenant_name")
    op.execute("DROP INDEX IF EXISTS idx_protocol_todo_block_status")
    op.execute("DROP INDEX IF EXISTS idx_finance_transaction_protocol")
    op.execute("DROP INDEX IF EXISTS idx_template_participant_participant")
    op.execute("DROP INDEX IF EXISTS idx_template_tenant_status")
