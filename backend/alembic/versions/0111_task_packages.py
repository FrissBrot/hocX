"""Aufgabenpakete: wiederkehrende Aufgaben pro Zyklus, Verantwortliche aus Listen.

- task_package: das Paket selbst (z. B. "Sommerlager", "Scharleitung").
- task_package_cycle: Zuweisung eines Pakets an einen Zyklus ab einem Start-Zyklusjahr. Ein
  Paket kann mehreren Zyklen zugewiesen sein.
- task_package_item: eine Aufgabe im Paket mit Verantwortlichen (Listenzeilen oder feste
  Personen, gleiche Form wie die Verantwortlichen im Protokoll), Wiederholung und Fälligkeit.
- protocol_todo_assignee: mehrere Verantwortliche pro Todo. assigned_participant_id bleibt
  bestehen (erste Person), damit bestehende Leser unverändert funktionieren.
- protocol_todo erhält die Verknüpfung zur Paket-Aufgabe, Zyklus, Zyklusjahr und einen
  Wiederholungsschlüssel (eine Instanz je Aufgabe/Zyklus/Jahr/Wiederholung) sowie
  overridden_fields (von Hand geänderte Felder, die das Paket nicht mehr überschreibt).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0111_task_packages"
down_revision = "0110_protocol_template_pref"
branch_labels = None
depends_on = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    ]


def upgrade() -> None:
    op.create_table(
        "task_package",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True, server_default=sa.text("uuidv7()")),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("TRUE")),
        *_timestamps(),
        sa.UniqueConstraint("tenant_id", "name", name="uq_task_package_tenant_name"),
    )
    op.create_index("idx_task_package_tenant", "task_package", ["tenant_id"])

    op.create_table(
        "task_package_cycle",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True, server_default=sa.text("uuidv7()")),
        sa.Column("task_package_id", sa.BigInteger(), sa.ForeignKey("task_package.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cycle_config_id", sa.BigInteger(), sa.ForeignKey("cycle_config.id", ondelete="CASCADE"), nullable=False),
        sa.Column("start_cycle_year", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("task_package_id", "cycle_config_id", name="uq_task_package_cycle_package_config"),
    )
    op.create_index("idx_task_package_cycle_config", "task_package_cycle", ["cycle_config_id"])

    op.create_table(
        "task_package_item",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True, server_default=sa.text("uuidv7()")),
        sa.Column("task_package_id", sa.BigInteger(), sa.ForeignKey("task_package.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sort_index", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("task", sa.Text(), nullable=False),
        sa.Column("reference_link", sa.Text()),
        sa.Column("tags", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("responsible_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("recurrence_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{\"type\": \"once\"}'::jsonb")),
        sa.Column("due_rule_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{\"type\": \"none\"}'::jsonb")),
        *_timestamps(),
    )
    op.create_index("idx_task_package_item_package_sort", "task_package_item", ["task_package_id", "sort_index"])

    op.create_table(
        "protocol_todo_assignee",
        sa.Column("protocol_todo_id", sa.BigInteger(), sa.ForeignKey("protocol_todo.id", ondelete="CASCADE"), nullable=False),
        sa.Column("participant_id", sa.BigInteger(), sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sort_index", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.PrimaryKeyConstraint("protocol_todo_id", "participant_id", name="pk_protocol_todo_assignee"),
    )
    op.create_index("idx_protocol_todo_assignee_participant", "protocol_todo_assignee", ["participant_id"])

    op.add_column("protocol_todo", sa.Column("task_package_item_id", sa.BigInteger(), sa.ForeignKey("task_package_item.id", ondelete="SET NULL", name="fk_protocol_todo_task_package_item")))
    op.add_column("protocol_todo", sa.Column("cycle_config_id", sa.BigInteger(), sa.ForeignKey("cycle_config.id", ondelete="SET NULL", name="fk_protocol_todo_cycle_config")))
    op.add_column("protocol_todo", sa.Column("cycle_year", sa.Integer()))
    op.add_column("protocol_todo", sa.Column("occurrence_key", sa.Text()))
    op.add_column("protocol_todo", sa.Column("overridden_fields", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.create_index(
        "uq_protocol_todo_package_occurrence",
        "protocol_todo",
        ["task_package_item_id", "cycle_config_id", "cycle_year", "occurrence_key"],
        unique=True,
        postgresql_where=sa.text("task_package_item_id IS NOT NULL"),
    )
    op.create_index("idx_protocol_todo_cycle", "protocol_todo", ["cycle_config_id", "cycle_year"])

    for table in ("task_package", "task_package_cycle", "task_package_item", "protocol_todo_assignee"):
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO hocx_app")
    for sequence in ("task_package_id_seq", "task_package_cycle_id_seq", "task_package_item_id_seq"):
        op.execute(f"GRANT USAGE, SELECT ON SEQUENCE {sequence} TO hocx_app")


def downgrade() -> None:
    op.drop_index("idx_protocol_todo_cycle", table_name="protocol_todo")
    op.drop_index("uq_protocol_todo_package_occurrence", table_name="protocol_todo")
    for column in ("overridden_fields", "occurrence_key", "cycle_year", "cycle_config_id", "task_package_item_id"):
        op.drop_column("protocol_todo", column)
    op.drop_table("protocol_todo_assignee")
    op.drop_table("task_package_item")
    op.drop_table("task_package_cycle")
    op.drop_table("task_package")
