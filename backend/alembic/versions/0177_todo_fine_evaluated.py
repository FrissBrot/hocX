"""Pendenzen-Bussen: Merker «Busse für diesen Abschluss bewertet» (protocol_todo.fine_evaluated_at).

Eingefrorene Bussen bleiben seit dem Bereichs-Audit 2026-11 stehen, auch wenn eine Pendenz wieder
geöffnet, umterminiert oder neu zugewiesen wird. Damit ein Abschluss genau einmal bewertet wird -
auch wenn der Datenbank-Trigger der Abgabebox die Pendenz ohne Python erledigt und der Abgleich
erst Tage später läuft -, merkt sich die Pendenz, wann ihre Busse bewertet wurde. Bestehende
Abschlüsse gelten als bewertet, ausser frisch erledigte (letzte 2 Tage) ohne Busse: die bewertet
der nächste Abgleich wie bisher.

Revision ID: 0177_todo_fine_evaluated
Revises: 0176_list_group_source
Create Date: 2026-11-12
"""

from alembic import op

revision = "0177_todo_fine_evaluated"
down_revision = "0176_list_group_source"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE protocol_todo ADD COLUMN IF NOT EXISTS fine_evaluated_at timestamptz")
    op.execute(
        """
        UPDATE protocol_todo AS t
        SET fine_evaluated_at = t.completed_at
        WHERE t.completed_at IS NOT NULL
          AND (
            t.completed_at < now() - interval '2 days'
            OR EXISTS (SELECT 1 FROM todo_fine f WHERE f.protocol_todo_id = t.id)
          )
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE protocol_todo DROP COLUMN IF EXISTS fine_evaluated_at")
