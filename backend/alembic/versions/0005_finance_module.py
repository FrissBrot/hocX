"""add finance_account and finance_transaction tables

Revision ID: 0005_finance_module
Revises: 0004_protocol_version_final
Create Date: 2026-04-02
"""
from __future__ import annotations

from alembic import op


revision = "0005_finance_module"
down_revision = "0004_protocol_version_final"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS finance_account (
            id BIGSERIAL PRIMARY KEY,
            tenant_id BIGINT NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            currency_label TEXT NOT NULL DEFAULT 'CHF',
            description TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_finance_account_tenant ON finance_account (tenant_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS finance_transaction (
            id BIGSERIAL PRIMARY KEY,
            account_id BIGINT NOT NULL REFERENCES finance_account(id) ON DELETE CASCADE,
            amount NUMERIC(15,2) NOT NULL,
            description TEXT NOT NULL,
            transaction_date DATE NOT NULL,
            protocol_id BIGINT REFERENCES protocol(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_finance_transaction_account ON finance_transaction (account_id, transaction_date)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS finance_transaction")
    op.execute("DROP TABLE IF EXISTS finance_account")
