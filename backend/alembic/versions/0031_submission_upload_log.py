"""submission upload attempt log table"""

revision = "0031_submission_upload_log"
down_revision = "0030_trigger_sec_definer"

import sqlalchemy as sa
from alembic import op

ROLE_NAME = "hocx_abgabebox"


def upgrade():
    op.create_table(
        "submission_upload_log",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("assignment_id", sa.BigInteger, sa.ForeignKey("submission_assignment.id", ondelete="CASCADE"), nullable=False),
        sa.Column("element_ref", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("idx_upload_log_assignment_element", "submission_upload_log", ["assignment_id", "element_ref"])
    op.execute(f"GRANT INSERT ON submission_upload_log TO {ROLE_NAME}")
    op.execute(f"GRANT USAGE ON SEQUENCE submission_upload_log_id_seq TO {ROLE_NAME}")


def downgrade():
    op.execute(f"REVOKE INSERT ON submission_upload_log FROM {ROLE_NAME}")
    op.execute(f"REVOKE USAGE ON SEQUENCE submission_upload_log_id_seq FROM {ROLE_NAME}")
    op.drop_index("idx_upload_log_assignment_element", table_name="submission_upload_log")
    op.drop_table("submission_upload_log")
