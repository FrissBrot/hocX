"""participant_join_leave_dates: adds joined_at/left_at to participant, so a
participant can be excluded from attendance rosters of protocols dated before
they joined or after they left, without deleting their history.

Revision ID: 0047_participant_join_leave
Revises: 0046_word_import_profile
Create Date: 2026-08-04
"""

import sqlalchemy as sa
from alembic import op

revision = "0047_participant_join_leave"
down_revision = "0046_word_import_profile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("participant", sa.Column("joined_at", sa.Date(), nullable=True))
    op.add_column("participant", sa.Column("left_at", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("participant", "left_at")
    op.drop_column("participant", "joined_at")
