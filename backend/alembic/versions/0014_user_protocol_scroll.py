"""user protocol scroll position

Revision ID: 0014_user_protocol_scroll
Revises: 0013_fine_status_deleted
Create Date: 2026-07-02
"""
from alembic import op
import sqlalchemy as sa

revision = '0014_user_protocol_scroll'
down_revision = '0013_fine_status_deleted'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'user_protocol_scroll',
        sa.Column('user_id', sa.Integer, sa.ForeignKey('app_user.id', ondelete='CASCADE'), nullable=False),
        sa.Column('protocol_id', sa.Integer, sa.ForeignKey('protocol.id', ondelete='CASCADE'), nullable=False),
        sa.Column('scroll_y', sa.Integer, nullable=False, server_default='0'),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('user_id', 'protocol_id'),
    )


def downgrade():
    op.drop_table('user_protocol_scroll')
