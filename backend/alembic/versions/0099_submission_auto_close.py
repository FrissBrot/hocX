"""Abgaben koennen Elemente nach einer Abgabe automatisch schliessen: submission_assignment.auto_close

- 'never' (Default, alle bestehenden Abgaben): bisheriges Verhalten, ein Element bleibt nach
  einer Abgabe offen, bis das Zeitfenster/der Stichtag endet oder es manuell geschlossen wird.
- 'first_upload': die erste erfolgreiche Abgabe ueber die Abgabebox schliesst das Element.
- 'max_files': das Element schliesst, sobald max_files_per_element Dateien abgegeben wurden
  (ohne max_files_per_element = unbegrenzt schliesst es nie automatisch).

Geschlossen wird ueber eine zusaetzliche submission_upload-Zeile mit status='closed' (wie beim
manuellen Schliessen), die das abgabebox-backend in derselben Transaktion wie die Abgabe
schreibt - "Wieder aufschalten" funktioniert dadurch unveraendert. Die Rolle hocx_abgabebox
braucht keine neuen Rechte: submission_assignment ist bereits tabellenweit lesbar, und auf
submission_upload darf sie schon INSERT.

Revision ID: 0099_submission_auto_close
Revises: 0098_canonical_element_type_ids
Create Date: 2026-10-04
"""

import sqlalchemy as sa
from alembic import op

revision = "0099_submission_auto_close"
down_revision = "0098_canonical_element_type_ids"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "submission_assignment",
        sa.Column("auto_close", sa.Text(), nullable=False, server_default=sa.text("'never'")),
    )
    op.create_check_constraint(
        "ck_submission_assignment_auto_close",
        "submission_assignment",
        "auto_close IN ('never', 'first_upload', 'max_files')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_submission_assignment_auto_close", "submission_assignment", type_="check")
    op.drop_column("submission_assignment", "auto_close")
