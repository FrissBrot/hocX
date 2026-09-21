"""Indexed exact upload deduplication, retaining the original hash after conversion."""
from alembic import op
import sqlalchemy as sa

revision = "0082_upload_exact_duplicates"
down_revision = "0081_gallery_live_photo"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("stored_file", sa.Column("source_checksum_sha256", sa.Text(), nullable=True))
    op.create_index("idx_stored_file_tenant_checksum", "stored_file", ["tenant_id", "checksum_sha256"])
    op.create_index("idx_stored_file_tenant_source_checksum", "stored_file", ["tenant_id", "source_checksum_sha256"])


def downgrade():
    op.drop_index("idx_stored_file_tenant_source_checksum", table_name="stored_file")
    op.drop_index("idx_stored_file_tenant_checksum", table_name="stored_file")
    op.drop_column("stored_file", "source_checksum_sha256")
