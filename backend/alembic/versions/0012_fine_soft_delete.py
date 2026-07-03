"""fine soft delete: add delete_comment column

Revision ID: 0012_fine_soft_delete
Revises: 0011_fine_closed_in_protocol
Create Date: 2026-07-02
"""
from alembic import op
import sqlalchemy as sa

revision = '0012_fine_soft_delete'
down_revision = '0011_fine_closed_in_protocol'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('attendance_fine', sa.Column('delete_comment', sa.Text, nullable=True))


def downgrade():
    op.drop_column('attendance_fine', 'delete_comment')
