"""default track_changes_enabled to true (opt-out, not opt-in)

The feature is meant to be on by default while preparing a protocol, with an explicit
switch to turn it off - 0044 shipped it defaulting to false, which meant nothing ever
got marked until someone discovered and flipped the toggle. Flip the column default and
backfill existing rows (no protocol has relied on the false default yet - the feature
just shipped).

Revision ID: 0045_track_changes_default_on
Revises: 0044_track_changes
Create Date: 2026-07-31
"""

import sqlalchemy as sa
from alembic import op

revision = "0045_track_changes_default_on"
down_revision = "0044_track_changes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("protocol", "track_changes_enabled", server_default="true")
    op.execute(sa.text("UPDATE protocol SET track_changes_enabled = true WHERE track_changes_enabled = false"))


def downgrade() -> None:
    op.alter_column("protocol", "track_changes_enabled", server_default="false")
