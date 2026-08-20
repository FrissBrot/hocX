"""add is_session_marker to event so auto-generated next-session markers are hidden from the Termine overview list"""

revision = "0060_event_is_session_marker"
down_revision = "0056_submission_flexible_window"

import sqlalchemy as sa
from alembic import op


def upgrade():
    op.add_column(
        "event",
        sa.Column("is_session_marker", sa.Boolean, nullable=False, server_default=sa.text("false")),
    )
    op.execute(
        """
        UPDATE event
        SET is_session_marker = true
        WHERE id IN (SELECT next_event_id FROM template WHERE next_event_id IS NOT NULL)
           OR (description = 'Generated from session date block'
               AND id NOT IN (SELECT event_id FROM protocol WHERE event_id IS NOT NULL))
        """
    )


def downgrade():
    op.drop_column("event", "is_session_marker")
