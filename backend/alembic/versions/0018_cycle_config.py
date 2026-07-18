"""cycle_config: extract cycle settings from template into standalone entity

Revision ID: 0018_cycle_config
Revises: 0017_event_cycle
Create Date: 2026-07-03
"""

from alembic import op
import sqlalchemy as sa

revision = "0018_cycle_config"
down_revision = "0017_event_cycle"
branch_labels = None
depends_on = None


def upgrade():
    # 1. Create cycle_config table
    op.create_table(
        "cycle_config",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("reset_month", sa.SmallInteger(), nullable=False),
        sa.Column("reset_day", sa.SmallInteger(), nullable=False),
        sa.Column("name_pattern", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        # Temporary column for data migration mapping
        sa.Column("_origin_template_id", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # 2. Migrate: one CycleConfig per template that has cycle settings
    op.execute("""
        INSERT INTO cycle_config (tenant_id, name, reset_month, reset_day, name_pattern, _origin_template_id)
        SELECT
            tenant_id,
            COALESCE(cycle_name_pattern, 'Zyklus'),
            COALESCE(cycle_reset_month, 12),
            COALESCE(cycle_reset_day, 31),
            cycle_name_pattern,
            id
        FROM template
        WHERE cycle_reset_month IS NOT NULL OR cycle_name_pattern IS NOT NULL
    """)

    # 3. Add cycle_config_id FK to template
    op.add_column("template", sa.Column("cycle_config_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_template_cycle_config", "template", "cycle_config",
        ["cycle_config_id"], ["id"], ondelete="SET NULL",
    )
    op.execute("""
        UPDATE template t
        SET cycle_config_id = cc.id
        FROM cycle_config cc
        WHERE cc._origin_template_id = t.id
    """)

    # 4. Migrate event_cycle: template_id → cycle_config_id
    op.add_column("event_cycle", sa.Column("cycle_config_id", sa.BigInteger(), nullable=True))
    op.execute("""
        UPDATE event_cycle ec
        SET cycle_config_id = t.cycle_config_id
        FROM template t
        WHERE t.id = ec.template_id AND t.cycle_config_id IS NOT NULL
    """)
    # Drop rows that couldn't be mapped (template had no cycle config)
    op.execute("DELETE FROM event_cycle WHERE cycle_config_id IS NULL")
    op.alter_column("event_cycle", "cycle_config_id", nullable=False)
    op.create_foreign_key(
        "fk_event_cycle_config", "event_cycle", "cycle_config",
        ["cycle_config_id"], ["id"], ondelete="CASCADE",
    )

    # 5. Rebuild event_cycle PK and indexes
    op.drop_constraint("pk_event_cycle", "event_cycle", type_="primary")
    op.drop_index("idx_event_cycle_template_year", table_name="event_cycle")
    op.drop_constraint("event_cycle_template_id_fkey", "event_cycle", type_="foreignkey")
    op.drop_column("event_cycle", "template_id")
    op.create_primary_key("pk_event_cycle", "event_cycle", ["event_id", "cycle_config_id", "cycle_year"])
    op.create_index("idx_event_cycle_config_year", "event_cycle", ["cycle_config_id", "cycle_year"])

    # 6. Drop old cycle columns from template
    op.drop_column("template", "cycle_reset_month")
    op.drop_column("template", "cycle_reset_day")
    op.drop_column("template", "cycle_name_pattern")

    # 7. Drop migration helper column
    op.drop_column("cycle_config", "_origin_template_id")


def downgrade():
    # Re-add columns to template
    op.add_column("template", sa.Column("cycle_name_pattern", sa.Text(), nullable=True))
    op.add_column("template", sa.Column("cycle_reset_day", sa.SmallInteger(), nullable=True))
    op.add_column("template", sa.Column("cycle_reset_month", sa.SmallInteger(), nullable=True))

    # Restore template cycle values from cycle_config
    op.execute("""
        UPDATE template t
        SET cycle_reset_month = cc.reset_month,
            cycle_reset_day = cc.reset_day,
            cycle_name_pattern = cc.name_pattern
        FROM cycle_config cc
        WHERE cc.id = t.cycle_config_id
    """)

    # Restore event_cycle.template_id
    op.add_column("event_cycle", sa.Column("template_id", sa.BigInteger(), nullable=True))
    op.execute("""
        UPDATE event_cycle ec
        SET template_id = t.id
        FROM template t
        WHERE t.cycle_config_id = ec.cycle_config_id
    """)
    op.execute("DELETE FROM event_cycle WHERE template_id IS NULL")
    op.alter_column("event_cycle", "template_id", nullable=False)
    op.create_foreign_key(None, "event_cycle", "template", ["template_id"], ["id"], ondelete="CASCADE")

    op.drop_constraint("pk_event_cycle", "event_cycle", type_="primary")
    op.drop_index("idx_event_cycle_config_year", table_name="event_cycle")
    op.drop_constraint("fk_event_cycle_config", "event_cycle", type_="foreignkey")
    op.drop_column("event_cycle", "cycle_config_id")
    op.create_primary_key("pk_event_cycle", "event_cycle", ["event_id", "template_id", "cycle_year"])
    op.create_index("idx_event_cycle_template_year", "event_cycle", ["template_id", "cycle_year"])

    op.drop_constraint("fk_template_cycle_config", "template", type_="foreignkey")
    op.drop_column("template", "cycle_config_id")
    op.drop_table("cycle_config")
