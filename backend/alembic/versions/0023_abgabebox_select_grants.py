"""Grant SELECT on abgabebox tables for RETURNING clause

Revision ID: 0023_abgabebox_select_grants
Revises: 0022_abgabebox_seq_usage
Create Date: 2026-07-08
"""

from alembic import op

revision = "0023_abgabebox_select_grants"
down_revision = "0022_abgabebox_seq_usage"
branch_labels = None
depends_on = None

ROLE_NAME = "hocx_abgabebox"
TABLES = [
    "submission_upload_file",
    "stored_file",
    "submission_upload",
    "tenant",
    "submission_assignment",
]


def upgrade() -> None:
    for table in TABLES:
        op.execute(f"GRANT SELECT ON {table} TO {ROLE_NAME}")


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"REVOKE SELECT ON {table} FROM {ROLE_NAME}")
