"""add cycle_name_pattern to template

Revision ID: 0016_cycle_name_pattern
Revises: 0015_scroll_to_element_id
Create Date: 2026-07-03
"""
from alembic import op
import sqlalchemy as sa

revision = '0016_cycle_name_pattern'
down_revision = '0015_scroll_to_element_id'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('template', sa.Column('cycle_name_pattern', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('template', 'cycle_name_pattern')
