"""replace app_user.name with GENERATED ALWAYS AS (display_name) STORED

Revision ID: 0010_appuser_name_generated
Revises: 0009_indexes_and_constraints
Create Date: 2026-05-03
"""
from __future__ import annotations

from alembic import op


revision = "0010_appuser_name_generated"
down_revision = "0009_indexes_and_constraints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the manually-synced duplicate column and replace with a stored
    # generated column so the DB always mirrors display_name automatically.
    op.execute("ALTER TABLE app_user DROP COLUMN IF EXISTS name")
    op.execute(
        "ALTER TABLE app_user ADD COLUMN name TEXT GENERATED ALWAYS AS (display_name) STORED"
    )


def downgrade() -> None:
    # Revert to a plain TEXT column pre-populated from display_name.
    op.execute("ALTER TABLE app_user DROP COLUMN IF EXISTS name")
    op.execute("ALTER TABLE app_user ADD COLUMN name TEXT NOT NULL DEFAULT ''")
    op.execute("UPDATE app_user SET name = display_name")
    op.execute("ALTER TABLE app_user ALTER COLUMN name DROP DEFAULT")
