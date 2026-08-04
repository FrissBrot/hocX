"""word_import_profile: reusable heading/table-role mapping learned from previous
docx imports, so importing another file with the same legacy layout against the
same protocol template can skip fuzzy re-guessing.

Revision ID: 0046_word_import_profile
Revises: 0045_track_changes_default_on
Create Date: 2026-08-02
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0046_word_import_profile"
down_revision = "0045_track_changes_default_on"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "word_import_profile",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("template_id", sa.BigInteger(), nullable=True),
        sa.Column("mapping_config_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["template_id"], ["template.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "template_id", name="uq_word_import_profile_tenant_template"),
    )
    op.create_index("idx_word_import_profile_tenant", "word_import_profile", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("idx_word_import_profile_tenant", table_name="word_import_profile")
    op.drop_table("word_import_profile")
