"""Todo-Notizen und verknüpfte Dateien

- protocol_todo.notes: freier Markdown-Text, nur im Todo-Popup der Todo-Liste sichtbar
  (bewusst nicht in ProtocolTodoRead, Übersicht, Protokoll-Momentaufnahme oder Export).
- protocol_todo_file: verknüpft bereits hochgeladene Dateien (stored_file) mit einem Todo.
  Beide Fremdschlüssel CASCADE: Löschen des Todos oder der Datei entfernt nur die Verknüpfung.

Revision ID: 0128_todo_notes_files
Revises: 0127_cashflow
Create Date: 2026-10-17
"""

import sqlalchemy as sa
from alembic import op

revision = "0128_todo_notes_files"
down_revision = "0127_cashflow"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("protocol_todo", sa.Column("notes", sa.Text(), nullable=True))
    op.create_table(
        "protocol_todo_file",
        sa.Column("protocol_todo_id", sa.BigInteger(), sa.ForeignKey("protocol_todo.id", ondelete="CASCADE"), nullable=False),
        sa.Column("stored_file_id", sa.BigInteger(), sa.ForeignKey("stored_file.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sort_index", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("protocol_todo_id", "stored_file_id", name="pk_protocol_todo_file"),
    )
    op.create_index("idx_protocol_todo_file_stored_file", "protocol_todo_file", ["stored_file_id"])


def downgrade() -> None:
    op.drop_index("idx_protocol_todo_file_stored_file", table_name="protocol_todo_file")
    op.drop_table("protocol_todo_file")
    op.drop_column("protocol_todo", "notes")
