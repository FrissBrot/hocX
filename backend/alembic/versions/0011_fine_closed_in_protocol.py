"""fine: add closed_in_protocol_id for cross-protocol tracking

Revision ID: 0011_fine_closed_in_protocol
Revises: 0010_appuser_name_generated
Create Date: 2026-07-02
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0011_fine_closed_in_protocol"
down_revision = "0010_appuser_name_generated"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "attendance_fine",
        sa.Column("closed_in_protocol_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_attendance_fine_closed_protocol",
        "attendance_fine",
        "protocol",
        ["closed_in_protocol_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "idx_attendance_fine_closed_protocol",
        "attendance_fine",
        ["closed_in_protocol_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_attendance_fine_closed_protocol", table_name="attendance_fine")
    op.drop_constraint("fk_attendance_fine_closed_protocol", "attendance_fine", type_="foreignkey")
    op.drop_column("attendance_fine", "closed_in_protocol_id")
