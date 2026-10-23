"""Priorität bei Überlast je Abo (Nutzerentscheid 2026-10-23, Nachtrag zum Lasttest).

plan.load_priority: 0 = niedrig, 1 = normal, 2 = hoch. Wird es knapp, weist die Request-Annahme
(app/core/db_admission.py) zuerst neue Nutzer von Mandanten mit niedriger Priorität ab; wer schon
arbeitet, bleibt drin. Wartende Requests bekommen freie Plätze in der Reihenfolge der Priorität.
Alle bestehenden Pläne starten auf "normal" - die Stufen setzt der Plattform-Admin im Preiskatalog.

overload_rejection: Protokoll der Abweisungen, je Prozess alle ~15 s zusammengefasst (Mandant,
Stufe, Anzahl, verschiedene Nutzer). Wird nur bei Überlast geschrieben. Plattformdaten ohne RLS
wie system_error_log: nur das Adminportal liest sie, geschrieben wird ohne Mandantenbindung.

Revision ID: 0151_overload_priority
Revises: 0150_document_render_job
Create Date: 2026-10-23
"""

import sqlalchemy as sa
from alembic import op

revision = "0151_overload_priority"
down_revision = "0150_document_render_job"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("plan", sa.Column("load_priority", sa.SmallInteger(), nullable=False, server_default=sa.text("1")))
    op.create_check_constraint("ck_plan_load_priority", "plan", "load_priority BETWEEN 0 AND 2")
    op.create_table(
        "overload_rejection",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("instance", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=True),
        sa.Column("load_priority", sa.SmallInteger(), nullable=False),
        sa.Column("rejected", sa.Integer(), nullable=False),
        sa.Column("users", sa.Integer(), nullable=False),
        sa.Column("pressure_percent", sa.Integer(), nullable=False),
    )
    op.create_index("idx_overload_rejection_created", "overload_rejection", ["created_at"])
    op.create_index("idx_overload_rejection_tenant", "overload_rejection", ["tenant_id", "created_at"])


def downgrade() -> None:
    op.drop_table("overload_rejection")
    op.drop_constraint("ck_plan_load_priority", "plan", type_="check")
    op.drop_column("plan", "load_priority")
