"""public_id: backfills a fresh uuidv7() into every existing row's public_id column
added (nullable) in 0066_public_id_add_columns. Step 2 of the additive rollout - see
0065_public_id_function and 0068_public_id_constraints for the surrounding steps.

Plain single-statement UPDATE per table, not chunked: this is an internal group-
management tool, not a high-volume multi-tenant SaaS - table sizes at migration time
don't warrant the extra complexity of batched backfill loops. If a specific deployment's
table turns out to be large enough that a single UPDATE causes an unacceptable lock
duration, re-run this step manually in batches before the constraints migration; the
'WHERE public_id IS NULL' guard makes it safe to stop and resume.

Revision ID: 0067_public_id_backfill
Revises: 0066_public_id_add_columns
Create Date: 2026-08-25
"""

from alembic import op

revision = "0067_public_id_backfill"
down_revision = "0066_public_id_add_columns"
branch_labels = None
depends_on = None

TABLES = [
    "tenant",
    "platform_oidc_config",
    "tenant_domain",
    "app_user",
    "user_mfa_factor",
    "platform_admin",
    "group_entity",
    "leader",
    "participant",
    "event",
    "cycle_config",
    "word_import_profile",
    "word_import_suggestion_outcome",
    "word_import_document",
    "list_definition",
    "list_entry",
    "document_template",
    "document_template_part",
    "template",
    "element_definition",
    "template_element",
    "template_element_block",
    "protocol",
    "protocol_element",
    "protocol_element_block",
    "stored_file",
    "protocol_text",
    "protocol_display_snapshot",
    "protocol_todo",
    "protocol_image",
    "protocol_export_cache",
    "finance_account",
    "finance_transaction",
    "attendance_fine",
    "submission_assignment",
    "submission_upload",
    "submission_upload_file",
    "submission_upload_log",
    "system_error_log",
]


def upgrade() -> None:
    for table in TABLES:
        op.execute(f"UPDATE {table} SET public_id = uuidv7() WHERE public_id IS NULL")


def downgrade() -> None:
    # Nothing to undo: leaving backfilled values in place is harmless (they're still
    # nullable at this point) and 0066's downgrade drops the column outright anyway.
    pass
