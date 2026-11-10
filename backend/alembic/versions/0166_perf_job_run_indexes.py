"""Performance: record_job_run ohne Scan über den ganzen Verlauf, überflüssige Indizes weg.

record_job_run prüft bei Jobs ohne vollständigen Verlauf den Status des letzten Laufs. Die
Abfrage `WHERE job_name = $1 ORDER BY id DESC LIMIT 1` läuft in plpgsql mit einem generischen
Plan, der rückwärts über den Primärschlüssel scannt und alle Läufe anderer Jobs verwirft (im
Testbestand 13-15 ms pro Aufruf, mit wachsendem Verlauf mehr; zusammen über 40 % der gesamten
DB-Ausführungszeit). Über `max(id)` greift idx_system_job_run_job_id als Index-Only-Scan
(0,1 ms). Die Abfrage läuft ausserdem nur noch, wenn ihr Ergebnis überhaupt gebraucht wird.

Indizes, die nur Schreibaufwand kosten:
- idx_protocol_element_block_configuration_gin: GIN über das ganze Dokument, die einzigen
  @>-Abfragen (Datenexport) gehen auf Teilpfade (`-> 'attendance_entries'`) und können ihn
  nicht nutzen. Er wird bei jedem Autosave eines Blocks mitgeschrieben.
- idx_protocol_element_block_sort / idx_protocol_element_protocol_sort: identisch mit den
  Unique-Constraints auf (protocol_element_id, sort_index) bzw. (protocol_id, sort_index).
- idx_audit_log_tenant: identisch mit idx_audit_log_tenant_created (0143).

Revision ID: 0166_perf_job_run_indexes
Revises: 0165_event_field_config
Create Date: 2026-11-09
"""

from alembic import op

revision = "0166_perf_job_run_indexes"
down_revision = "0165_event_field_config"
branch_labels = None
depends_on = None


def _record_job_run(last_status_lookup: str) -> str:
    return r"""
        CREATE OR REPLACE FUNCTION public.record_job_run(
            p_job_name text, p_status text, p_started_at timestamptz, p_finished_at timestamptz,
            p_error text, p_keep_history boolean
        ) RETURNS void
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
        DECLARE
          v_duration_ms integer := GREATEST(0, LEAST(2147483647, (EXTRACT(EPOCH FROM (p_finished_at - p_started_at)) * 1000)::bigint))::integer;
          v_error text := CASE WHEN p_error IS NULL THEN NULL ELSE left(p_error, 4000) END;
          v_keep boolean;
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
          v_keep := p_keep_history OR p_status = 'failure';
          IF NOT v_keep THEN
            v_keep := COALESCE((""" + last_status_lookup + r"""), '') <> 'success';
          END IF;
          IF v_keep THEN
            INSERT INTO public.system_job_run (job_name, status, started_at, finished_at, duration_ms, error)
            VALUES (p_job_name, p_status, p_started_at, p_finished_at, v_duration_ms, v_error);
          END IF;
        END
        $$
    """


# max(id) statt ORDER BY id DESC LIMIT 1: der generische Plan nimmt sonst den Primärschlüssel.
_FAST_LOOKUP = (
    "SELECT r.status FROM public.system_job_run r WHERE r.id = ("
    "SELECT max(r2.id) FROM public.system_job_run r2 WHERE r2.job_name = p_job_name)"
)
_OLD_LOOKUP = "SELECT r.status FROM public.system_job_run r WHERE r.job_name = p_job_name ORDER BY r.id DESC LIMIT 1"


def upgrade() -> None:
    # CREATE OR REPLACE behält Besitzer und EXECUTE-Rechte der Funktion.
    op.execute(_record_job_run(_FAST_LOOKUP))
    op.execute("DROP INDEX IF EXISTS idx_protocol_element_block_configuration_gin")
    op.execute("DROP INDEX IF EXISTS idx_protocol_element_block_sort")
    op.execute("DROP INDEX IF EXISTS idx_protocol_element_protocol_sort")
    op.execute("DROP INDEX IF EXISTS idx_audit_log_tenant")


def downgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_tenant ON audit_log (tenant_id, created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_protocol_element_protocol_sort ON protocol_element (protocol_id, sort_index)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_protocol_element_block_sort ON protocol_element_block (protocol_element_id, sort_index)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_protocol_element_block_configuration_gin "
        "ON protocol_element_block USING gin (configuration_snapshot_json)"
    )
    op.execute(_record_job_run(_OLD_LOOKUP))
