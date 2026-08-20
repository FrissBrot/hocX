"""add last_word_import_template_id to tenant so the import wizard's template dropdown remembers the last selection"""

revision = "0061_tenant_last_word_import"
down_revision = "0060_event_is_session_marker"

import sqlalchemy as sa
from alembic import op


def upgrade():
    op.add_column(
        "tenant",
        sa.Column("last_word_import_template_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_tenant_last_word_import_template_id",
        "tenant",
        "template",
        ["last_word_import_template_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade():
    op.drop_constraint("fk_tenant_last_word_import_template_id", "tenant", type_="foreignkey")
    op.drop_column("tenant", "last_word_import_template_id")
