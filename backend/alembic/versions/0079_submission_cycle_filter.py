"""Abgaben (Termin-Quelle) koennen auf Zyklen eingeschraenkt werden: cycle_config_id +
cycle_offsets (0 = aktueller Zyklus, -1 = vorheriger, ...).

Ohne cycle_config_id (Default, alle bestehenden Abgaben) gilt weiterhin: alle Termine mit dem
Tag-Filter, unabhaengig vom Zyklus. Mit Zyklus-Konfiguration werden nur Termine beruecksichtigt,
die per event_cycle einem der gewaehlten Zyklen zugeordnet sind.

cycle_config_id ist ON DELETE RESTRICT: sonst wuerde das Loeschen der Zyklus-Konfiguration die
Abgabe stillschweigend wieder auf alle Termine ausweiten.

Isolation: die restricted Rolle hocx_abgabebox braucht (fuer die Zyklusberechnung im oeffentlichen
Service) Spalten-SELECT auf cycle_config (id, reset_month, reset_day) und event_cycle -
nichts sonst, nie name/name_pattern. submission_assignment ist bereits tabellenweit lesbar.
"""

revision = "0079_submission_cycle_filter"
down_revision = "0078_single_tenant_users"
branch_labels = None
depends_on = None

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

ABGABEBOX_ROLE = "hocx_abgabebox"


def upgrade():
    op.add_column(
        "submission_assignment",
        sa.Column("cycle_config_id", sa.BigInteger(), sa.ForeignKey("cycle_config.id", ondelete="RESTRICT")),
    )
    op.add_column(
        "submission_assignment",
        sa.Column("cycle_offsets", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    op.create_index("idx_submission_assignment_cycle_config", "submission_assignment", ["cycle_config_id"])
    op.create_check_constraint(
        "ck_submission_assignment_cycle_filter",
        "submission_assignment",
        "(cycle_config_id IS NULL AND jsonb_array_length(cycle_offsets) = 0) OR "
        "(cycle_config_id IS NOT NULL AND source_type = 'events' AND jsonb_array_length(cycle_offsets) > 0)",
    )

    op.execute(f"GRANT SELECT (id, reset_month, reset_day) ON TABLE cycle_config TO {ABGABEBOX_ROLE}")
    op.execute(f"GRANT SELECT (event_id, cycle_config_id, cycle_year) ON TABLE event_cycle TO {ABGABEBOX_ROLE}")


def downgrade():
    op.execute(f"REVOKE SELECT ON TABLE event_cycle FROM {ABGABEBOX_ROLE}")
    op.execute(f"REVOKE SELECT ON TABLE cycle_config FROM {ABGABEBOX_ROLE}")
    op.drop_constraint("ck_submission_assignment_cycle_filter", "submission_assignment", type_="check")
    op.drop_index("idx_submission_assignment_cycle_config", table_name="submission_assignment")
    op.drop_column("submission_assignment", "cycle_offsets")
    op.drop_column("submission_assignment", "cycle_config_id")
