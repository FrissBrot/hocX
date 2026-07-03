"""fine status: add 'deleted' to allowed status values

Revision ID: 0013_fine_status_deleted
Revises: 0012_fine_soft_delete
Create Date: 2026-07-02
"""
from alembic import op

revision = '0013_fine_status_deleted'
down_revision = '0012_fine_soft_delete'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE attendance_fine DROP CONSTRAINT attendance_fine_status_check")
    op.execute("ALTER TABLE attendance_fine ADD CONSTRAINT attendance_fine_status_check CHECK (status = ANY (ARRAY['pending'::text, 'collected'::text, 'deleted'::text]))")


def downgrade():
    op.execute("ALTER TABLE attendance_fine DROP CONSTRAINT attendance_fine_status_check")
    op.execute("ALTER TABLE attendance_fine ADD CONSTRAINT attendance_fine_status_check CHECK (status = ANY (ARRAY['pending'::text, 'collected'::text]))")
