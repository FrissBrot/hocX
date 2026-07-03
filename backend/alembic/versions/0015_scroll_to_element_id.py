"""rename scroll_y to last_element_id in user_protocol_scroll

Revision ID: 0015_scroll_to_element_id
Revises: 0014_user_protocol_scroll
Create Date: 2026-07-03
"""
from alembic import op

revision = '0015_scroll_to_element_id'
down_revision = '0014_user_protocol_scroll'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column('user_protocol_scroll', 'scroll_y', new_column_name='last_element_id')


def downgrade():
    op.alter_column('user_protocol_scroll', 'last_element_id', new_column_name='scroll_y')
