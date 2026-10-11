"""Job-Übersicht im Platform-Admin (/admin/jobs): letzter Lauf, Dauer, Fehler und Verlauf jedes
periodischen Jobs - Backend-Loops, abgabebox-Loop, photo-analysis-worker und künftig Host-Cronjobs.

system_job_status hält pro Job genau eine Zeile mit dem aktuellen Stand, system_job_run den
Verlauf (Aufräumen über log_cleanup_loop). Welche Jobs es geben *sollte* und wie lange sie
höchstens still sein dürfen, steht bewusst nicht hier, sondern in
backend/app/core/job_registry.py - die Tabelle enthält nur, was tatsächlich gemeldet wurde.

Geschrieben wird ausschliesslich über die SECURITY-DEFINER-Funktionen record_job_run/
record_job_start/record_job_heartbeat: die eingeschränkten Rollen hocx_abgabebox und
hocx_photo_worker bekommen nur EXECUTE darauf, kein DML auf die Tabellen (gleiches Muster wie
upload_storage_usage in 0092). Host-Cronjobs melden über dieselben Funktionen per
`docker compose exec db psql`. hocx_app hat via ALTER DEFAULT PRIVILEGES ohnehin DML auf neuen
Tabellen (Lesen für die Admin-Seite, Löschen für die Retention).

Revision ID: 0105_system_job_status
Revises: 0104_tenant_show_on_website
Create Date: 2026-10-11
"""

import sqlalchemy as sa
from alembic import op

revision = "0105_system_job_status"
down_revision = "0104_tenant_show_on_website"
branch_labels = None
depends_on = None

_FUNCTION_SIGNATURES = (
    "record_job_run(text, text, timestamptz, timestamptz, text, boolean)",
    "record_job_start(text)",
    "record_job_heartbeat(text)",
)
_REPORTING_ROLES = "hocx_app, hocx_abgabebox, hocx_photo_worker"


def upgrade() -> None:
    op.create_table(
        "system_job_status",
        sa.Column("job_name", sa.Text(), primary_key=True),
        sa.Column("last_status", sa.Text(), nullable=True),
        sa.Column("last_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_duration_ms", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("run_count", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("failure_count", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint("last_status IN ('running', 'success', 'failure')", name="ck_system_job_status_last_status"),
    )
    op.create_table(
        "system_job_run",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("job_name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint("status IN ('success', 'failure')", name="ck_system_job_run_status"),
    )
    op.create_index("idx_system_job_run_job_id", "system_job_run", ["job_name", "id"])
    op.create_index("idx_system_job_run_finished", "system_job_run", ["finished_at"])

    # Jobnamen werden validiert, weil auch Host-Skripte und die eingeschränkten Rollen frei
    # melden dürfen: ein Tippfehler soll laut scheitern statt als neuer Phantom-Job aufzutauchen
    # bzw. die Tabelle mit beliebigem Text zu füllen. Fehlermeldungen werden gekürzt, damit ein
    # riesiger Traceback die Übersicht nicht sprengt (der volle Traceback steht in system_error_log).
    op.execute(r"""
        CREATE FUNCTION public.record_job_run(
            p_job_name text, p_status text, p_started_at timestamptz, p_finished_at timestamptz,
            p_error text, p_keep_history boolean
        ) RETURNS void
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
        DECLARE
          v_duration_ms integer := GREATEST(0, LEAST(2147483647, (EXTRACT(EPOCH FROM (p_finished_at - p_started_at)) * 1000)::bigint))::integer;
          v_error text := CASE WHEN p_error IS NULL THEN NULL ELSE left(p_error, 4000) END;
        BEGIN
          IF p_job_name !~ '^[a-z0-9][a-z0-9_.-]{0,99}$' THEN
            RAISE EXCEPTION 'invalid job name: %', p_job_name;
          END IF;
          IF p_status NOT IN ('success', 'failure') THEN
            RAISE EXCEPTION 'invalid job status: %', p_status;
          END IF;

          INSERT INTO public.system_job_status AS s (
            job_name, last_status, last_started_at, last_finished_at, last_success_at, last_failure_at,
            last_duration_ms, last_error, consecutive_failures, run_count, failure_count, updated_at
          ) VALUES (
            p_job_name, p_status, p_started_at, p_finished_at,
            CASE WHEN p_status = 'success' THEN p_finished_at END,
            CASE WHEN p_status = 'failure' THEN p_finished_at END,
            v_duration_ms, v_error,
            CASE WHEN p_status = 'failure' THEN 1 ELSE 0 END,
            1,
            CASE WHEN p_status = 'failure' THEN 1 ELSE 0 END,
            NOW()
          )
          ON CONFLICT (job_name) DO UPDATE SET
            last_status = EXCLUDED.last_status,
            last_started_at = EXCLUDED.last_started_at,
            last_finished_at = EXCLUDED.last_finished_at,
            last_success_at = COALESCE(EXCLUDED.last_success_at, s.last_success_at),
            last_failure_at = COALESCE(EXCLUDED.last_failure_at, s.last_failure_at),
            last_duration_ms = EXCLUDED.last_duration_ms,
            -- Letzte Fehlermeldung bleibt nach einem Erfolg sichtbar (mit last_failure_at), damit
            -- ein sporadischer Fehler nicht beim nächsten grünen Lauf spurlos verschwindet.
            last_error = COALESCE(EXCLUDED.last_error, s.last_error),
            consecutive_failures = CASE WHEN p_status = 'failure' THEN s.consecutive_failures + 1 ELSE 0 END,
            run_count = s.run_count + 1,
            failure_count = s.failure_count + EXCLUDED.failure_count,
            updated_at = NOW();

          -- Hochfrequente Jobs (z. B. gallery_upload_ingest alle 5 s) würden den Verlauf mit
          -- Erfolgsmeldungen fluten - dort werden nur Fehler und der erste Erfolg danach behalten.
          IF p_keep_history OR p_status = 'failure' OR COALESCE((
            SELECT r.status FROM public.system_job_run r WHERE r.job_name = p_job_name ORDER BY r.id DESC LIMIT 1
          ), '') <> 'success' THEN
            INSERT INTO public.system_job_run (job_name, status, started_at, finished_at, duration_ms, error)
            VALUES (p_job_name, p_status, p_started_at, p_finished_at, v_duration_ms, v_error);
          END IF;
        END
        $$
    """)
    op.execute(r"""
        CREATE FUNCTION public.record_job_start(p_job_name text) RETURNS void
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
        BEGIN
          IF p_job_name !~ '^[a-z0-9][a-z0-9_.-]{0,99}$' THEN
            RAISE EXCEPTION 'invalid job name: %', p_job_name;
          END IF;
          INSERT INTO public.system_job_status AS s (job_name, last_status, last_started_at, updated_at)
          VALUES (p_job_name, 'running', NOW(), NOW())
          ON CONFLICT (job_name) DO UPDATE SET last_status = 'running', last_started_at = NOW(), updated_at = NOW();
        END
        $$
    """)
    op.execute(r"""
        CREATE FUNCTION public.record_job_heartbeat(p_job_name text) RETURNS void
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
        BEGIN
          IF p_job_name !~ '^[a-z0-9][a-z0-9_.-]{0,99}$' THEN
            RAISE EXCEPTION 'invalid job name: %', p_job_name;
          END IF;
          INSERT INTO public.system_job_status AS s (job_name, last_heartbeat_at, updated_at)
          VALUES (p_job_name, NOW(), NOW())
          ON CONFLICT (job_name) DO UPDATE SET last_heartbeat_at = NOW(), updated_at = NOW();
        END
        $$
    """)
    for signature in _FUNCTION_SIGNATURES:
        op.execute(f"REVOKE ALL ON FUNCTION public.{signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION public.{signature} TO {_REPORTING_ROLES}")


def downgrade() -> None:
    for signature in _FUNCTION_SIGNATURES:
        op.execute(f"DROP FUNCTION public.{signature}")
    op.drop_table("system_job_run")
    op.drop_table("system_job_status")
