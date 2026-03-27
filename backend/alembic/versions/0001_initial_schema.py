"""initial hocx schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-03-27 00:00:00
"""

from pathlib import Path

from alembic import op


revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql_path = Path(__file__).resolve().parents[2] / "sql" / "first_setup.sql"
    op.execute(sql_path.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute(
        """
DROP FUNCTION IF EXISTS create_protocol_from_template(BIGINT, BIGINT, TEXT, DATE, BIGINT, TEXT, BIGINT);
DROP TABLE IF EXISTS protocol_export_cache;
DROP TABLE IF EXISTS protocol_image;
DROP TABLE IF EXISTS protocol_todo;
DROP TABLE IF EXISTS todo_status;
DROP TABLE IF EXISTS protocol_display_snapshot;
DROP TABLE IF EXISTS protocol_text;
DROP TABLE IF EXISTS stored_file;
DROP TABLE IF EXISTS protocol_element_block;
DROP TABLE IF EXISTS protocol_element;
DROP TABLE IF EXISTS protocol;
DROP TABLE IF EXISTS template_element_block;
DROP TABLE IF EXISTS template_element;
DROP TABLE IF EXISTS element_definition;
DROP TABLE IF EXISTS template;
DROP TABLE IF EXISTS render_type;
DROP TABLE IF EXISTS element_type;
DROP TABLE IF EXISTS document_template_part;
DROP TABLE IF EXISTS document_template;
DROP TABLE IF EXISTS event;
DROP TABLE IF EXISTS event_category;
DROP TABLE IF EXISTS leader;
DROP TABLE IF EXISTS group_entity;
DROP TABLE IF EXISTS user_tenant_role;
DROP TABLE IF EXISTS user_role;
DROP TABLE IF EXISTS app_user;
DROP TABLE IF EXISTS role;
DROP TABLE IF EXISTS tenant;
DROP FUNCTION IF EXISTS set_updated_at();
        """
    )
