"""Todo-Momentaufnahme abgeschlossener Protokolle.

Todos bleiben nach dem Abschluss ihres Protokolls bearbeitbar (auch löschen/anlegen). Damit
das abgeschlossene Protokoll weiterhin den Stand beim Abschluss zeigt, wird dieser in
protocol.todos_snapshot_json eingefroren und beim Zurücksetzen verworfen.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0112_protocol_todos_snapshot"
down_revision = "0111_task_packages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("protocol", sa.Column("todos_snapshot_json", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("protocol", "todos_snapshot_json")
