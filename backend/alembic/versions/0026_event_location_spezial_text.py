"""add location and spezial_text fields to event"""

revision = "0026_event_location_spezial_text"
down_revision = "0025_event_participant_roles"

import sqlalchemy as sa
from alembic import op

COLUMNS = ["location", "spezial_text1", "spezial_text2", "spezial_text3"]


def upgrade():
    for col in COLUMNS:
        op.add_column("event", sa.Column(col, sa.Text, nullable=True))


def downgrade():
    for col in reversed(COLUMNS):
        op.drop_column("event", col)
