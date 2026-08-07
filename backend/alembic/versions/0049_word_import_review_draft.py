"""word_import_document: add review_draft_json - caches the reviewer's in-progress edits
(candidate links, approve toggles, corrected values) so leaving the page or reloading
mid-review doesn't lose them, mirroring the existing analysis_snapshot_json cache.

Revision ID: 0049_word_import_review_draft
Revises: 0048_word_import_document
Create Date: 2026-08-06
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0049_word_import_review_draft"
down_revision = "0048_word_import_document"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "word_import_document",
        sa.Column("review_draft_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )


def downgrade() -> None:
    op.drop_column("word_import_document", "review_draft_json")
