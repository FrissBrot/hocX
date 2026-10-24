"""Zentrales Wartungssystem: dauerhaft gespeicherte Wartungsfenster mit Zuständen,
Freigabebedingungen, Schätzung und Verlauf.

- maintenance_window: ein Wartungsgrund (z. B. Erstmigration, Cutover, manuelle Wartung).
  Mehrere Fenster können gleichzeitig blockieren; die Anwendung ist gesperrt, solange irgendein
  blockierendes Fenster besteht (siehe app/services/maintenance_service.py).
  'failed' blockiert bewusst weiter - ein fehlgeschlagener Job hebt die Sperre nie auf.
- maintenance_event: Verlauf/Audit jeder Zustandsänderung und Admin-Aktion.
- maintenance_effective_state(): kompakte, sichere Sicht für Dienste mit eingeschränkter
  DB-Rolle (abgabebox) - ob voll gesperrt bzw. Schreibzugriffe gesperrt sind.

Revision ID: 0114_maintenance
Revises: 0113_object_storage
Create Date: 2026-10-14
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0114_maintenance"
down_revision = "0113_object_storage"
branch_labels = None
depends_on = None

STATES = ("scheduled", "preparing", "active", "verifying", "completed", "failed", "overdue", "cancelled")
BLOCKING_STATES = ("preparing", "active", "verifying", "failed", "overdue")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.create_table(
        "maintenance_window",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        # full = Anwendung gesperrt; partial = nur die in block_scope genannten Bereiche.
        sa.Column("kind", sa.Text(), nullable=False),
        # all | writes | uploads - welche Betriebsphase gesperrt wird.
        sa.Column("block_scope", sa.Text(), nullable=False, server_default=sa.text("'all'")),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("reason_code", sa.Text(), nullable=False),
        sa.Column("affected_features", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        # Öffentlicher Text je Sprache ({"de": "...", "en": "..."}); leer = Standardtext im Frontend.
        sa.Column("public_message", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("internal_note", sa.Text(), nullable=True),
        sa.Column("source_job_type", sa.Text(), nullable=True),
        sa.Column("source_job_id", sa.Text(), nullable=True),
        sa.Column("scheduled_start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scheduled_end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        # Schätzung (Sekunden ab started_at bzw. ab estimate_updated_at für die Restdauer).
        sa.Column("estimate", postgresql.JSONB(), nullable=True),
        sa.Column("estimated_end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("original_estimated_end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("safety_margin_seconds", sa.Integer(), nullable=True),
        sa.Column("estimate_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("progress", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        # [{"key": "...", "params": {...}}] - geprüft vom Backend, nie vom Job selbst.
        sa.Column("release_conditions", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("warnings", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_by_email", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint("kind IN ('full', 'partial')", name="ck_maintenance_window_kind"),
        sa.CheckConstraint("block_scope IN ('all', 'writes', 'uploads')", name="ck_maintenance_window_scope"),
        sa.CheckConstraint(f"state IN ({_in(STATES)})", name="ck_maintenance_window_state"),
    )
    op.create_index(
        "idx_maintenance_window_blocking", "maintenance_window", ["state"],
        postgresql_where=sa.text(f"state IN ({_in(BLOCKING_STATES)})"),
    )
    op.create_index("idx_maintenance_window_created", "maintenance_window", ["created_at"])

    op.create_table(
        "maintenance_event",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("window_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("maintenance_window.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("actor_email", sa.Text(), nullable=True),
        sa.Column("from_state", sa.Text(), nullable=True),
        sa.Column("to_state", sa.Text(), nullable=True),
        sa.Column("details", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.create_index("idx_maintenance_event_window", "maintenance_event", ["window_id", "id"])

    op.execute(rf"""
        CREATE FUNCTION public.maintenance_effective_state()
        RETURNS TABLE (full_active boolean, writes_blocked boolean, uploads_blocked boolean, estimated_end_at timestamptz)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
          SELECT
            COALESCE(bool_or(kind = 'full'), false),
            COALESCE(bool_or(kind = 'full' OR block_scope IN ('all', 'writes')), false),
            COALESCE(bool_or(kind = 'full' OR block_scope IN ('all', 'writes', 'uploads')), false),
            max(estimated_end_at)
          FROM public.maintenance_window
          WHERE state IN ({_in(BLOCKING_STATES)})
        $$
    """)
    op.execute("REVOKE ALL ON FUNCTION public.maintenance_effective_state() FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION public.maintenance_effective_state() TO hocx_app, hocx_abgabebox, hocx_photo_worker")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS public.maintenance_effective_state()")
    op.drop_table("maintenance_event")
    op.drop_table("maintenance_window")
