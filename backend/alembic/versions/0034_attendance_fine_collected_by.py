"""add collected_by_user_id to attendance_fine"""

revision = "0034_fine_collected_by"
down_revision = "0033_platform_admin"

import sqlalchemy as sa
from alembic import op


def upgrade():
    op.add_column(
        "attendance_fine",
        sa.Column("collected_by_user_id", sa.BigInteger, sa.ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("idx_attendance_fine_collected_by", "attendance_fine", ["collected_by_user_id"])


def downgrade():
    op.drop_index("idx_attendance_fine_collected_by", table_name="attendance_fine")
    op.drop_column("attendance_fine", "collected_by_user_id")
