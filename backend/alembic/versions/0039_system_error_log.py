"""system_error_log: app-wide captured backend errors, visible only in the admin panel

Revision ID: 0039_system_error_log
Revises: 0038_tenant_domain_health
Create Date: 2026-07-25

Also grants INSERT on this table to the restricted 'hocx_abgabebox' role (see
0020_abgabebox.py) so the public, unauthenticated Abgabebox service can record its own
errors too - deliberately no SELECT grant, that role must never be able to read back
anything, including its own error rows (matches the existing INSERT-only pattern for
submission_upload/submission_upload_file/stored_file - like those, `id` is a plain
Identity column, which needs no separate sequence GRANT once INSERT is granted).
"""

import sqlalchemy as sa
from alembic import op

revision = "0039_system_error_log"
down_revision = "0038_tenant_domain_health"
branch_labels = None
depends_on = None

ROLE_NAME = "hocx_abgabebox"


def upgrade() -> None:
    op.create_table(
        "system_error_log",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=True),
        sa.Column("actor_email", sa.Text(), nullable=True),
        sa.Column("request_method", sa.Text(), nullable=True),
        sa.Column("request_path", sa.Text(), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("error_type", sa.Text(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("traceback", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("source IN ('backend', 'abgabebox-backend')", name="ck_system_error_log_source"),
    )
    op.create_index("idx_system_error_log_created", "system_error_log", ["created_at"])
    op.create_index("idx_system_error_log_tenant", "system_error_log", ["tenant_id", "created_at"])
    op.create_index("idx_system_error_log_type", "system_error_log", ["error_type", "created_at"])

    op.execute(f"GRANT INSERT ON system_error_log TO {ROLE_NAME}")


def downgrade() -> None:
    op.execute(f"REVOKE INSERT ON system_error_log FROM {ROLE_NAME}")
    op.drop_table("system_error_log")
