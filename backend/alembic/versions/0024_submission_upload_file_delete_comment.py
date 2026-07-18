"""Add delete_comment to submission_upload_file

Revision ID: 0024_upload_file_delete_comment
Revises: 0023_abgabebox_select_grants
Create Date: 2026-07-08
"""

import sqlalchemy as sa
from alembic import op

revision = "0024_upload_file_delete_comment"
down_revision = "0023_abgabebox_select_grants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "submission_upload_file",
        sa.Column("delete_comment", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("submission_upload_file", "delete_comment")
