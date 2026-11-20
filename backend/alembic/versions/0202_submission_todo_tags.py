"""Abgaben: Tags für die Pendenzen der Abgabe.

``todo_tags`` sind frei gewählte Tags, die jede Pendenz der Abgabe bekommt; ``todo_own_tag``
gibt zusätzlich ein eigenes Tag mit dem Titel der Abgabe (standardmässig aus). Der Abgleich
(submission_service.sync_submission_todos) setzt sie auf jede Pendenz und nimmt bei einer
Änderung nur die vorher vorgegebenen Tags weg - von Hand ergänzte bleiben.

Rein additiv: neue Spalten mit Vorgabe, keine Datenänderung. Die Abgabebox liest die Spalten
nicht (ihre Tabellendefinition nennt die Spalten einzeln).

Revision ID: 0202_submission_todo_tags
Revises: 0201_abgabebox_scan_status
Create Date: 2026-11-20
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0202_submission_todo_tags"
down_revision = "0201_abgabebox_scan_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "submission_assignment",
        sa.Column("todo_tags", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    op.add_column(
        "submission_assignment",
        sa.Column("todo_own_tag", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("submission_assignment", "todo_own_tag")
    op.drop_column("submission_assignment", "todo_tags")
