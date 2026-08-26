"""adds indexes for the 31 foreign-key columns that had none (audit finding, 2026-08-26 -
found by cross-referencing information_schema's FK constraints against pg_index: every FK
column that was never the leading column of any index on its table). Invisible at today's
row counts, but FK joins, WHERE-filters, and ON DELETE SET NULL/CASCADE/RESTRICT checks on
these columns force a sequential scan of the whole table once real data accumulates.

Uses CREATE INDEX CONCURRENTLY (via op.get_context().autocommit_block(), one index per
autocommit block since CONCURRENTLY can't run inside a transaction) rather than the plain
CREATE INDEX every prior migration used - audit finding, 2026-08-26: a plain CREATE INDEX
takes a lock that blocks writes to the table for the build's duration, and
`alembic upgrade head` runs automatically before every deploy (docker-compose.yml). Fine
at today's table sizes, but adopting CONCURRENTLY now avoids ever having to remember to
switch approaches once a table is large enough for that lock to matter. Trade-off: if a
CONCURRENTLY build is interrupted (e.g. killed mid-deploy), it can leave an INVALID index
behind that needs a manual `DROP INDEX CONCURRENTLY IF EXISTS <name>` before re-running
this migration - see https://www.postgresql.org/docs/current/sql-createindex.html.

Revision ID: 0071_missing_fk_indexes
Revises: 0070_restrict_app_db_role
Create Date: 2026-08-26
"""

from alembic import op

revision = "0071_missing_fk_indexes"
down_revision = "0070_restrict_app_db_role"
branch_labels = None
depends_on = None

# (index_name, table, column)
INDEXES = [
    ("idx_attendance_fine_collected_transaction", "attendance_fine", "collected_transaction_id"),
    ("idx_event_category_id", "event", "event_category_id"),
    ("idx_event_group_id", "event", "group_id"),
    ("idx_participant_app_user_id", "participant", "app_user_id"),
    ("idx_protocol_created_by", "protocol", "created_by"),
    ("idx_protocol_element_template_element", "protocol_element", "template_element_id"),
    ("idx_protocol_element_block_element_definition", "protocol_element_block", "element_definition_id"),
    ("idx_protocol_element_block_render_type", "protocol_element_block", "render_type_id"),
    ("idx_protocol_element_block_template_element_block", "protocol_element_block", "template_element_block_id"),
    ("idx_protocol_export_cache_generated_file", "protocol_export_cache", "generated_file_id"),
    ("idx_protocol_image_stored_file", "protocol_image", "stored_file_id"),
    ("idx_protocol_todo_closed_in_protocol", "protocol_todo", "closed_in_protocol_id"),
    ("idx_protocol_todo_created_by", "protocol_todo", "created_by"),
    ("idx_stored_file_created_by", "stored_file", "created_by"),
    ("idx_submission_assignment_list_definition", "submission_assignment", "list_definition_id"),
    ("idx_submission_upload_event", "submission_upload", "event_id"),
    ("idx_submission_upload_list_entry", "submission_upload", "list_entry_id"),
    ("idx_submission_upload_file_stored_file", "submission_upload_file", "stored_file_id"),
    ("idx_template_created_by", "template", "created_by"),
    ("idx_template_cycle_config", "template", "cycle_config_id"),
    ("idx_template_element_element_definition", "template_element", "element_definition_id"),
    ("idx_template_element_block_element_definition", "template_element_block", "element_definition_id"),
    ("idx_tenant_last_word_import_template", "tenant", "last_word_import_template_id"),
    ("idx_user_protocol_scroll_protocol", "user_protocol_scroll", "protocol_id"),
    ("idx_user_role_role", "user_role", "role_id"),
    ("idx_word_import_document_created_by", "word_import_document", "created_by"),
    ("idx_word_import_document_imported_by", "word_import_document", "imported_by"),
    ("idx_word_import_document_stored_file", "word_import_document", "stored_file_id"),
    ("idx_word_import_document_template", "word_import_document", "template_id"),
    ("idx_word_import_profile_template", "word_import_profile", "template_id"),
    ("idx_word_import_suggestion_outcome_template", "word_import_suggestion_outcome", "template_id"),
]


def upgrade() -> None:
    for index_name, table, column in INDEXES:
        with op.get_context().autocommit_block():
            op.execute(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {index_name} ON {table} ({column})")


def downgrade() -> None:
    for index_name, _table, _column in reversed(INDEXES):
        with op.get_context().autocommit_block():
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {index_name}")
