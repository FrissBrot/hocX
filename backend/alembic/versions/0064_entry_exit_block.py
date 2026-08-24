"""entry_exit_block: adds the 'entry_exit' element_type ("Ein-/Austritte") - a computed
block that lists participant joins/leaves (Participant.joined_at/left_at) since the block's
prior use in an earlier protocol of the same template, so consecutive protocols never repeat
the same entry/exit.

Also resyncs element_type_id_seq to MAX(id): rows 12-15 (finance_balance/finance_transactions/
fine_list/chart) were inserted with explicit ids outside the sequence at some point (by a
one-off manual statement, not a migration), leaving the sequence stuck at 6 - a plain insert
that lets Postgres assign the id (like this migration's, or any future one) would otherwise
collide with an existing row.

Revision ID: 0064_entry_exit_block
Revises: 0061_tenant_last_word_import
Create Date: 2026-08-24
"""

from alembic import op

revision = "0064_entry_exit_block"
down_revision = "0061_tenant_last_word_import"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SELECT setval('element_type_id_seq', (SELECT MAX(id) FROM element_type))")
    op.execute(
        """
        INSERT INTO element_type (code, description)
        VALUES ('entry_exit', 'Participant entry/exit block')
        ON CONFLICT (code) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM element_type WHERE code = 'entry_exit'")
