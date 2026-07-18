"""Add participant role columns to event table

Revision ID: 0025_event_participant_roles
Revises: 0024_upload_file_delete_comment
Create Date: 2026-07-08
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0025_event_participant_roles"
down_revision = "0024_upload_file_delete_comment"
branch_labels = None
depends_on = None

COLUMNS = [
    "organizer_ids",
    "leadership_ids",
    "participant_ids",
    "spezial1_ids",
    "spezial2_ids",
    "spezial3_ids",
]


def upgrade() -> None:
    for col in COLUMNS:
        op.add_column(
            "event",
            sa.Column(col, JSONB, nullable=True),
        )


def downgrade() -> None:
    for col in COLUMNS:
        op.drop_column("event", col)
