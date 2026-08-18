"""add perceptual_hash to stored_file for tenant-wide image duplicate warnings"""

revision = "0057_stored_file_perceptual_hash"
down_revision = "0056_submission_flexible_window"

import sqlalchemy as sa
from alembic import op

def upgrade():
    op.add_column("stored_file", sa.Column("perceptual_hash", sa.Text, nullable=True))
    op.create_index(
        "idx_stored_file_tenant_perceptual_hash",
        "stored_file",
        ["tenant_id", "perceptual_hash"],
    )
    # abgabebox already has table-wide INSERT/SELECT on stored_file (0020/0023), which
    # covers this new column too - no extra GRANT needed.


def downgrade():
    op.drop_index("idx_stored_file_tenant_perceptual_hash", table_name="stored_file")
    op.drop_column("stored_file", "perceptual_hash")
