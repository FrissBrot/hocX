"""submission_assignment: optional time window, unlimited files, sort order, closable elements

Abgaben sollen optional ohne festes Zeitfenster (Tage vor/nach Termin bzw. Stichtag) auskommen
und stattdessen offen bleiben, bis sie manuell geschlossen werden. Dazu:

1. ck_submission_assignment_source_fields wird gelockert: offset_days_before/offset_days_after
   (Termin-Abgaben) und deadline (Listen-Abgaben) sind jetzt optional statt Pflicht.
2. max_files_per_element wird nullable (NULL = unbegrenzt viele Dateien).
3. Neue Spalte sort_order (alphabetical/date/proximity) steuert die Reihenfolge der Elemente,
   sowohl im Admin-Bereich als auch - unveraendert uebernommen - in der oeffentlichen Abgabebox.
4. submission_upload.status erlaubt neu 'closed' (manuelles Schliessen eines Elements, siehe
   SubmissionService.close_element/reopen_element). 'reopened' bleibt fuer historische Zeilen
   in der CHECK-Liste, wird aber nicht mehr neu erzeugt.

Revision ID: 0056_submission_flexible_window
Revises: 0055_pref_mfa_method
Create Date: 2026-08-17
"""

import sqlalchemy as sa
from alembic import op

revision = "0056_submission_flexible_window"
down_revision = "0055_pref_mfa_method"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_submission_assignment_source_fields", "submission_assignment", type_="check")
    op.create_check_constraint(
        "ck_submission_assignment_source_fields",
        "submission_assignment",
        "(source_type = 'events' AND tag_filter IS NOT NULL "
        "AND list_definition_id IS NULL AND deadline IS NULL) OR "
        "(source_type = 'list' AND list_definition_id IS NOT NULL "
        "AND tag_filter IS NULL AND offset_days_before IS NULL AND offset_days_after IS NULL)",
    )

    op.drop_constraint("ck_submission_assignment_max_files", "submission_assignment", type_="check")
    op.alter_column("submission_assignment", "max_files_per_element", nullable=True)
    op.create_check_constraint(
        "ck_submission_assignment_max_files",
        "submission_assignment",
        "max_files_per_element IS NULL OR max_files_per_element >= 1",
    )

    op.add_column(
        "submission_assignment",
        sa.Column("sort_order", sa.Text(), nullable=False, server_default=sa.text("'date'")),
    )
    op.create_check_constraint(
        "ck_submission_assignment_sort_order",
        "submission_assignment",
        "sort_order IN ('alphabetical', 'date', 'proximity')",
    )

    op.drop_constraint("ck_submission_upload_status", "submission_upload", type_="check")
    op.create_check_constraint(
        "ck_submission_upload_status",
        "submission_upload",
        "status IN ('submitted', 'reopened', 'closed')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_submission_upload_status", "submission_upload", type_="check")
    op.create_check_constraint(
        "ck_submission_upload_status",
        "submission_upload",
        "status IN ('submitted', 'reopened')",
    )

    op.drop_constraint("ck_submission_assignment_sort_order", "submission_assignment", type_="check")
    op.drop_column("submission_assignment", "sort_order")

    op.drop_constraint("ck_submission_assignment_max_files", "submission_assignment", type_="check")
    op.execute("UPDATE submission_assignment SET max_files_per_element = 5 WHERE max_files_per_element IS NULL")
    op.alter_column("submission_assignment", "max_files_per_element", nullable=False)
    op.create_check_constraint(
        "ck_submission_assignment_max_files",
        "submission_assignment",
        "max_files_per_element >= 1",
    )

    op.execute(
        "UPDATE submission_assignment SET offset_days_before = 0 "
        "WHERE source_type = 'events' AND offset_days_before IS NULL"
    )
    op.execute(
        "UPDATE submission_assignment SET offset_days_after = 0 "
        "WHERE source_type = 'events' AND offset_days_after IS NULL"
    )
    op.execute(
        "UPDATE submission_assignment SET deadline = CURRENT_DATE "
        "WHERE source_type = 'list' AND deadline IS NULL"
    )
    op.drop_constraint("ck_submission_assignment_source_fields", "submission_assignment", type_="check")
    op.create_check_constraint(
        "ck_submission_assignment_source_fields",
        "submission_assignment",
        "(source_type = 'events' AND tag_filter IS NOT NULL AND offset_days_before IS NOT NULL "
        "AND offset_days_after IS NOT NULL AND list_definition_id IS NULL AND deadline IS NULL) OR "
        "(source_type = 'list' AND list_definition_id IS NOT NULL AND deadline IS NOT NULL "
        "AND tag_filter IS NULL AND offset_days_before IS NULL AND offset_days_after IS NULL)",
    )
