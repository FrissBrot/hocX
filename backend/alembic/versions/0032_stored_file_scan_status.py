"""add scan_status to stored_file"""

revision = "0032_stored_file_scan_status"
down_revision = "0031_submission_upload_log"

import sqlalchemy as sa
from alembic import op

def upgrade():
    op.add_column(
        "stored_file",
        sa.Column("scan_status", sa.Text, nullable=False, server_default="clean"),
    )
    # abgabebox already has INSERT on stored_file and can write scan_status at INSERT time.
    # The main backend (hocx = DB owner) handles UPDATEs during rescan without extra grants.


def downgrade():
    op.drop_column("stored_file", "scan_status")
