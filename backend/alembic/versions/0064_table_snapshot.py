"""add table_snapshot (cycle snapshot feature)

Stores one row per (tenant, cycle_config, cycle_year, table_name): a frozen JSONB
array of that table's rows as of the cycle boundary. See
app/services/table_snapshot_service.py for how rows are written and
app/models/entities.py's TableSnapshot for the column docstring.

This is the first schema change on top of the 0001 baseline squash - a plain Alembic
revision (op.create_table/op.create_index), not a baseline_schema.sql edit (see 0001's
docstring: baseline_schema.sql is a frozen 1.0.0 snapshot, not an ongoing pattern to
extend). No explicit GRANTs are needed: baseline_schema.sql's `ALTER DEFAULT PRIVILEGES
... IN SCHEMA public GRANT ... ON TABLES TO hocx_app` applies to every table any future
migration creates under the same admin role that ran 0001, this one included.

Revision ID: 0064_table_snapshot
Revises: 0063_gallery_image
Create Date: 2026-09-04
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0064_table_snapshot"
down_revision = "0063_gallery_image"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "table_snapshot",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("uuidv7()")),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cycle_config_id", sa.BigInteger(), sa.ForeignKey("cycle_config.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cycle_year", sa.Integer(), nullable=False),
        sa.Column("table_name", sa.Text(), nullable=False),
        sa.Column("snapshot_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("is_edited", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("edited_by", sa.BigInteger(), sa.ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("public_id", name="uq_table_snapshot_public_id"),
        sa.UniqueConstraint(
            "tenant_id", "cycle_config_id", "cycle_year", "table_name",
            name="uq_table_snapshot_tenant_cycle_table",
        ),
    )
    op.create_index(
        "idx_table_snapshot_tenant_cycle",
        "table_snapshot",
        ["tenant_id", "cycle_config_id", "cycle_year"],
    )
    op.create_index(
        "idx_table_snapshot_json_gin",
        "table_snapshot",
        ["snapshot_json"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("idx_table_snapshot_json_gin", table_name="table_snapshot")
    op.drop_index("idx_table_snapshot_tenant_cycle", table_name="table_snapshot")
    op.drop_table("table_snapshot")
