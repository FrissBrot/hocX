"""create event_cycle junction table

Revision ID: 0017_event_cycle
Revises: 0016_cycle_name_pattern
Create Date: 2026-07-03
"""
from alembic import op
import sqlalchemy as sa

revision = '0017_event_cycle'
down_revision = '0016_cycle_name_pattern'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'event_cycle',
        sa.Column('event_id', sa.BigInteger(), nullable=False),
        sa.Column('template_id', sa.BigInteger(), nullable=False),
        sa.Column('cycle_year', sa.SmallInteger(), nullable=False),
        sa.ForeignKeyConstraint(['event_id'], ['event.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['template_id'], ['template.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('event_id', 'template_id', 'cycle_year', name='pk_event_cycle'),
    )
    op.create_index('idx_event_cycle_event', 'event_cycle', ['event_id'])
    op.create_index('idx_event_cycle_template_year', 'event_cycle', ['template_id', 'cycle_year'])


def downgrade():
    op.drop_index('idx_event_cycle_template_year', table_name='event_cycle')
    op.drop_index('idx_event_cycle_event', table_name='event_cycle')
    op.drop_table('event_cycle')
