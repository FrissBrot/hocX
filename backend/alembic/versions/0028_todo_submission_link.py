"""link protocol_todo to submission_assignment"""

revision = "0028_todo_submission_link"
down_revision = "0027_submission_resp_source"

import sqlalchemy as sa
from alembic import op


def upgrade():
    op.add_column("protocol_todo", sa.Column("submission_assignment_id", sa.BigInteger, nullable=True))
    op.add_column("protocol_todo", sa.Column("element_ref", sa.Text, nullable=True))
    op.create_foreign_key(
        "fk_protocol_todo_submission_assignment",
        "protocol_todo", "submission_assignment",
        ["submission_assignment_id"], ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "uix_protocol_todo_submission_element",
        "protocol_todo",
        ["submission_assignment_id", "element_ref"],
        unique=True,
        postgresql_where=sa.text("submission_assignment_id IS NOT NULL"),
    )


def downgrade():
    op.drop_index("uix_protocol_todo_submission_element", table_name="protocol_todo")
    op.drop_constraint("fk_protocol_todo_submission_assignment", "protocol_todo", type_="foreignkey")
    op.drop_column("protocol_todo", "element_ref")
    op.drop_column("protocol_todo", "submission_assignment_id")
