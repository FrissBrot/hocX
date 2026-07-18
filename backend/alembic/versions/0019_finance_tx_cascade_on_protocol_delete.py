"""finance_transaction: cascade delete when protocol is deleted

Revision ID: 0019_finance_tx_cascade_on_protocol_delete
Revises: 0018_cycle_config
Create Date: 2026-07-03
"""

from alembic import op

revision = "0019_finance_tx_cascade"
down_revision = "0018_cycle_config"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.drop_constraint("finance_transaction_protocol_id_fkey", "finance_transaction", type_="foreignkey")
    op.create_foreign_key(
        "finance_transaction_protocol_id_fkey",
        "finance_transaction", "protocol",
        ["protocol_id"], ["id"],
        ondelete="CASCADE",
    )

def downgrade() -> None:
    op.drop_constraint("finance_transaction_protocol_id_fkey", "finance_transaction", type_="foreignkey")
    op.create_foreign_key(
        "finance_transaction_protocol_id_fkey",
        "finance_transaction", "protocol",
        ["protocol_id"], ["id"],
        ondelete="SET NULL",
    )
