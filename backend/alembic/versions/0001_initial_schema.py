"""initial hocx schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-03-27 00:00:00
"""

from pathlib import Path

from alembic import context, op


revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql_path = Path(__file__).resolve().parents[2] / "sql" / "first_setup.sql"
    sql = sql_path.read_text(encoding="utf-8")
    seed_marker = "INSERT INTO tenant (name, profile_image_path) VALUES"
    seed_demo = context.get_x_argument(as_dictionary=True).get("seed_demo", "").lower() == "true"

    if seed_demo:
        # Demo identities have public, intentionally well-known credentials. They are only
        # installed when a developer explicitly opts in with `alembic -x seed_demo=true`.
        op.execute(sql)
        return

    # Everything before the marker is schema and global lookup data. Tenant-specific demo
    # rows must never be part of an ordinary migration (the production deploy path).
    schema_sql, marker, _demo_sql = sql.partition(seed_marker)
    if not marker:
        raise RuntimeError("first_setup.sql demo-seed marker is missing")
    op.execute(f"{schema_sql}\nCOMMIT;")


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
