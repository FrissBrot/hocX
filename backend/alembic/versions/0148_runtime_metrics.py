"""Laufzeitkennzahlen je Prozess (Concurrency-Audit, Paket 0): Event-Loop-Verzögerung, Belegung
von DB-Pool und Threadpool. Jeder Dienstprozess (Backend-Worker, Abgabebox-Worker, job-worker,
...) meldet alle ~15 s über record_runtime_metrics; /admin/system wertet die Zeilen der letzten
Minute aus (system_health_service._check_runtime).

Über die Datenbank statt Redis, weil die Abgabebox bewusst keinen Redis-Zugang hat. Gemeldet wird
über eine eigene, ungepoolte Verbindung - gerade bei erschöpftem Pool soll die Meldung ankommen.
Wie record_job_heartbeat: nur SECURITY-DEFINER-Funktion für die eingeschränkten Rollen, kein DML.

Revision ID: 0148_runtime_metrics
Revises: 0147_privacy_notice_location
Create Date: 2026-10-21
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0148_runtime_metrics"
down_revision = "0147_privacy_notice_location"
branch_labels = None
depends_on = None

_SIGNATURE = "record_runtime_metrics(text, text, jsonb)"
_REPORTING_ROLES = "hocx_app, hocx_abgabebox, hocx_photo_worker"


def upgrade() -> None:
    op.create_table(
        "system_runtime_metric",
        sa.Column("instance", sa.Text(), primary_key=True),
        sa.Column("process_kind", sa.Text(), nullable=False),
        sa.Column("reported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metrics", postgresql.JSONB(), nullable=False),
    )
    op.execute(r"""
        CREATE FUNCTION public.record_runtime_metrics(p_instance text, p_process_kind text, p_metrics jsonb)
        RETURNS void
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
        BEGIN
          IF p_instance !~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$' OR p_process_kind !~ '^[a-z0-9][a-z0-9_.-]{0,59}$' THEN
            RAISE EXCEPTION 'invalid runtime metric instance: %', p_instance;
          END IF;
          IF jsonb_typeof(p_metrics) <> 'object' OR length(p_metrics::text) > 4000 THEN
            RAISE EXCEPTION 'invalid runtime metrics payload';
          END IF;
          INSERT INTO public.system_runtime_metric AS m (instance, process_kind, reported_at, metrics)
          VALUES (p_instance, p_process_kind, NOW(), p_metrics)
          ON CONFLICT (instance) DO UPDATE SET process_kind = EXCLUDED.process_kind, reported_at = NOW(), metrics = EXCLUDED.metrics;
          -- Beendete Prozesse (neue PID nach Neustart) räumen sich so selbst weg.
          DELETE FROM public.system_runtime_metric WHERE reported_at < NOW() - interval '1 day';
        END
        $$
    """)
    op.execute(f"REVOKE ALL ON FUNCTION public.{_SIGNATURE} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION public.{_SIGNATURE} TO {_REPORTING_ROLES}")


def downgrade() -> None:
    op.execute(f"DROP FUNCTION IF EXISTS public.{_SIGNATURE}")
    op.drop_table("system_runtime_metric")
