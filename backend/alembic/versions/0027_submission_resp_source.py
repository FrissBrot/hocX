"""add responsible_participant_source to submission_assignment"""

revision = "0027_submission_resp_source"
down_revision = "0026_event_location_spezial_text"

import sqlalchemy as sa
from alembic import op


def upgrade():
    op.add_column("submission_assignment", sa.Column("responsible_participant_source", sa.Text, nullable=True))


def downgrade():
    op.drop_column("submission_assignment", "responsible_participant_source")
