"""word_import_document: queue row for the multi-document Word-Import tool - one row
per uploaded .docx (stored via stored_file), tracks whether it has only been read in
("eingelesen") or already turned into a protocol ("importiert"), and caches the last
analysis so review can be resumed without re-uploading.

Revision ID: 0048_word_import_document
Revises: 0047_participant_join_leave
Create Date: 2026-08-05
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0048_word_import_document"
down_revision = "0047_participant_join_leave"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "word_import_document",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("template_id", sa.BigInteger(), nullable=False),
        sa.Column("stored_file_id", sa.BigInteger(), nullable=False),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("protocol_date", sa.Date(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'eingelesen'")),
        sa.Column("analysis_snapshot_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("protocol_id", sa.BigInteger(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("imported_by", sa.BigInteger(), nullable=True),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["template_id"], ["template.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["stored_file_id"], ["stored_file.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["protocol_id"], ["protocol.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["app_user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["imported_by"], ["app_user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("status IN ('eingelesen', 'importiert')", name="ck_word_import_document_status"),
    )
    op.create_index(
        "idx_word_import_document_tenant_template_status",
        "word_import_document",
        ["tenant_id", "template_id", "status"],
    )
    op.create_index("idx_word_import_document_protocol", "word_import_document", ["protocol_id"])


def downgrade() -> None:
    op.drop_index("idx_word_import_document_protocol", table_name="word_import_document")
    op.drop_index("idx_word_import_document_tenant_template_status", table_name="word_import_document")
    op.drop_table("word_import_document")
