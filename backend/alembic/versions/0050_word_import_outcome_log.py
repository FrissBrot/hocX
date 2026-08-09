"""word_import_suggestion_outcome: append-only log of one row per resolved matching
decision at WordImportService.commit() time (event/participant/table-role/list-entry/
matrix-column match), recording the score the algorithm's top suggestion had and
whether the human kept it or picked something else. Used to compute per-tenant
accept-rate quality stats and, from that data, adaptive per-tenant score thresholds
(see the word_import_thresholds module added alongside this).

Revision ID: 0050_word_import_outcome_log
Revises: 0049_word_import_review_draft
Create Date: 2026-08-09

Note: the table itself is still named word_import_suggestion_outcome (matching the
ORM model) - only this revision id is shortened, since alembic_version.version_num is
varchar(32) and "0050_word_import_suggestion_outcome" (36 chars) doesn't fit.
"""

import sqlalchemy as sa
from alembic import op

revision = "0050_word_import_outcome_log"
down_revision = "0049_word_import_review_draft"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "word_import_suggestion_outcome",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("template_id", sa.BigInteger(), nullable=True),
        sa.Column("signal_type", sa.Text(), nullable=False),
        sa.Column("suggested_score", sa.Float(), nullable=False),
        sa.Column("was_accepted", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["template_id"], ["template.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_word_import_suggestion_outcome_lookup",
        "word_import_suggestion_outcome",
        ["tenant_id", "template_id", "signal_type"],
    )


def downgrade() -> None:
    op.drop_index("idx_word_import_suggestion_outcome_lookup", table_name="word_import_suggestion_outcome")
    op.drop_table("word_import_suggestion_outcome")
