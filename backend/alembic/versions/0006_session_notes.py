"""add session_notes to protocol table

Revision ID: 0006_session_notes
Revises: 0005_finance_module
Create Date: 2026-04-12
"""
from __future__ import annotations

from alembic import op


revision = "0006_session_notes"
down_revision = "0005_finance_module"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE protocol ADD COLUMN IF NOT EXISTS session_notes TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE protocol DROP COLUMN IF EXISTS session_notes")
