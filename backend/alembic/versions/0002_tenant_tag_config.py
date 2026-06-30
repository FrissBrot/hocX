"""add tag_config_json to tenant

Revision ID: 0002_tenant_tag_config
Revises: 0001_initial_schema
Create Date: 2026-04-02 00:00:00
"""

from alembic import op

revision = "0002_tenant_tag_config"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE tenant ADD COLUMN IF NOT EXISTS tag_config_json jsonb NOT NULL DEFAULT '{}'::jsonb;"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE tenant DROP COLUMN IF EXISTS tag_config_json;")
