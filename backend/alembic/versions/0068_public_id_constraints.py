"""public_id: verifies the 0067 backfill, then locks the public_id column down -
UNIQUE constraint, NOT NULL, and a server_default of uuidv7() for every future row.
Step 3 (final) of the additive rollout - see 0065_public_id_function,
0066_public_id_add_columns, 0067_public_id_backfill.

Verification runs first and raises before touching any schema if a table has a NULL
public_id, a duplicate, or a value that isn't a real UUIDv7 (wrong version nibble) -
per-table, so a failure names the offending table instead of failing opaquely on the
first ADD CONSTRAINT.

Revision ID: 0068_public_id_constraints
Revises: 0067_public_id_backfill
Create Date: 2026-08-25
"""

import sqlalchemy as sa
from alembic import op

revision = "0068_public_id_constraints"
down_revision = "0067_public_id_backfill"
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


def _verify_table(bind: sa.engine.Connection, table: str) -> None:
    total, distinct_non_null, null_count, bad_version = bind.execute(
        sa.text(
            f"""
            SELECT
                count(*),
                count(DISTINCT public_id),
                count(*) FILTER (WHERE public_id IS NULL),
                count(*) FILTER (WHERE public_id IS NOT NULL AND substring(public_id::text FROM 15 FOR 1) != '7')
            FROM {table}
            """
        )
    ).one()

    if null_count:
        raise RuntimeError(f"public_id migration: {table} has {null_count} row(s) with NULL public_id after backfill")
    if distinct_non_null != total:
        raise RuntimeError(f"public_id migration: {table} has duplicate public_id values ({total} rows, {distinct_non_null} distinct)")
    if bad_version:
        raise RuntimeError(f"public_id migration: {table} has {bad_version} public_id value(s) that aren't UUIDv7")


def upgrade() -> None:
    bind = op.get_bind()
    for table in TABLES:
        _verify_table(bind, table)

    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ADD CONSTRAINT uq_{table}_public_id UNIQUE (public_id)")
        op.execute(f"ALTER TABLE {table} ALTER COLUMN public_id SET NOT NULL")
        op.execute(f"ALTER TABLE {table} ALTER COLUMN public_id SET DEFAULT uuidv7()")


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ALTER COLUMN public_id DROP DEFAULT")
        op.execute(f"ALTER TABLE {table} ALTER COLUMN public_id DROP NOT NULL")
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS uq_{table}_public_id")
