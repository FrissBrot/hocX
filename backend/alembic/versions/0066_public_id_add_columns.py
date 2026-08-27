"""public_id: adds a nullable public_id UUID column to every table with its own
standalone BIGINT primary key, as step 1 of the additive public_id rollout (see
0065_public_id_function, 0067_public_id_backfill, 0068_public_id_constraints).

Kept nullable and without a default here on purpose: adding a column with a *volatile*
default (uuidv7() is volatile - it reads the clock and random bytes) forces Postgres to
rewrite the whole table under an ACCESS EXCLUSIVE lock immediately, once per table, all
in this one migration. Splitting into nullable-add -> batched backfill -> constraints
(the next two migrations) keeps each step fast and independently verifiable instead of
one long lock across 38 tables.

Excluded from this list: composite-key join tables (user_role, user_tenant_role,
template_participant, user_template_access, user_protocol_access, event_cycle,
user_protocol_scroll - they're addressed via their owning entities, not directly) and
small lookup tables of controlled technical codes (role, event_category, element_type,
render_type, todo_status - not guessable entity ids, kept as plain small ints).

Revision ID: 0066_public_id_add_columns
Revises: 0065_public_id_function
Create Date: 2026-08-25
"""

from alembic import op

revision = "0066_public_id_add_columns"
down_revision = "0065_public_id_function"
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
        op.execute(f"ALTER TABLE {table} ADD COLUMN public_id UUID")


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS public_id")
