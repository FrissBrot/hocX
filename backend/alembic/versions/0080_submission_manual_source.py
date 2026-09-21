"""Manuelle Abgaben: source_type 'manual' - weder an Termine noch an eine Liste gekoppelt.

Eine manuelle Abgabe hat genau ein Element (die Abgabe selbst). Ihre Uploads tragen deshalb
weder event_id noch list_entry_id; der Zustand wird wie bei den anderen Quellen ueber
(assignment_id, event_id, list_entry_id) = (id, NULL, NULL) aufgeloest.

- ck_submission_assignment_source_type: 'manual' zusaetzlich erlaubt.
- ck_submission_assignment_source_fields: 'manual' darf weder tag_filter, list_definition_id noch
  Tage-Offsets haben; ein Stichtag (deadline) bleibt optional.
- ck_submission_upload_exactly_one_target -> ck_submission_upload_at_most_one_target: ein Upload
  darf jetzt auch ohne Ziel (event_id und list_entry_id NULL) sein, aber nie beides.

Die Rolle hocx_abgabebox braucht keine neuen Rechte: sie schreibt weiter nur INSERTs in
submission_upload, die CHECK-Regel gilt unabhaengig davon.
"""

revision = "0080_submission_manual_source"
down_revision = "0079_submission_cycle_filter"
branch_labels = None
depends_on = None

from alembic import op


def upgrade():
    op.drop_constraint("ck_submission_assignment_source_type", "submission_assignment", type_="check")
    op.create_check_constraint(
        "ck_submission_assignment_source_type",
        "submission_assignment",
        "source_type IN ('events', 'list', 'manual')",
    )
    op.drop_constraint("ck_submission_assignment_source_fields", "submission_assignment", type_="check")
    op.create_check_constraint(
        "ck_submission_assignment_source_fields",
        "submission_assignment",
        "(source_type = 'events' AND tag_filter IS NOT NULL "
        "AND list_definition_id IS NULL AND deadline IS NULL) OR "
        "(source_type = 'list' AND list_definition_id IS NOT NULL "
        "AND tag_filter IS NULL AND offset_days_before IS NULL AND offset_days_after IS NULL) OR "
        "(source_type = 'manual' AND tag_filter IS NULL AND list_definition_id IS NULL "
        "AND offset_days_before IS NULL AND offset_days_after IS NULL)",
    )
    op.drop_constraint("ck_submission_upload_exactly_one_target", "submission_upload", type_="check")
    op.create_check_constraint(
        "ck_submission_upload_at_most_one_target",
        "submission_upload",
        "event_id IS NULL OR list_entry_id IS NULL",
    )


def downgrade():
    op.execute("DELETE FROM submission_upload WHERE event_id IS NULL AND list_entry_id IS NULL")
    op.execute("DELETE FROM submission_assignment WHERE source_type = 'manual'")
    op.drop_constraint("ck_submission_upload_at_most_one_target", "submission_upload", type_="check")
    op.create_check_constraint(
        "ck_submission_upload_exactly_one_target",
        "submission_upload",
        "(event_id IS NOT NULL AND list_entry_id IS NULL) OR (event_id IS NULL AND list_entry_id IS NOT NULL)",
    )
    op.drop_constraint("ck_submission_assignment_source_fields", "submission_assignment", type_="check")
    op.create_check_constraint(
        "ck_submission_assignment_source_fields",
        "submission_assignment",
        "(source_type = 'events' AND tag_filter IS NOT NULL "
        "AND list_definition_id IS NULL AND deadline IS NULL) OR "
        "(source_type = 'list' AND list_definition_id IS NOT NULL "
        "AND tag_filter IS NULL AND offset_days_before IS NULL AND offset_days_after IS NULL)",
    )
    op.drop_constraint("ck_submission_assignment_source_type", "submission_assignment", type_="check")
    op.create_check_constraint(
        "ck_submission_assignment_source_type",
        "submission_assignment",
        "source_type IN ('events', 'list')",
    )
