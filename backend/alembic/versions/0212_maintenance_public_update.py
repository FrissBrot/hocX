"""Update-Seite auch in der Abgabebox: ``maintenance_public_update()``.

Die Abgabebox (Rolle ``hocx_abgabebox`` ohne Tabellenzugriff) liest den Wartungszustand nur über
``maintenance_effective_state()`` (0114). Damit sie während eines Updates dieselbe Update-Meldung
zeigt wie hocX (statt «Wartung»), liefert diese zweite SECURITY-DEFINER-Funktion nur, ob gerade
ausschliesslich ein Deploy-Fenster sperrt, die öffentlichen Versionen (alt → neu) und den Beginn.
Keine internen Angaben (Notizen, Fehler, Job-IDs ausser der Zielversion).

Revision ID: 0212_maintenance_public_update
Revises: 0210_email_delivery_status
Create Date: 2026-11-21
"""
from __future__ import annotations

from alembic import op

revision = "0212_maintenance_public_update"
down_revision = "0210_email_delivery_status"
branch_labels = None
depends_on = None

BLOCKING_STATES = "'preparing', 'active', 'verifying', 'failed', 'overdue'"


def upgrade() -> None:
    # update_active wie maintenance_service.public_status: nur wenn jedes volle, sperrende Fenster
    # ein Deploy-Fenster ist. Versionen aus dem ältesten Fenster; geprüft werden sie beim Schreiben
    # (maintenance_service.clean_version) und beim Lesen in der Abgabebox nochmals.
    op.execute(f"""
        CREATE FUNCTION public.maintenance_public_update()
        RETURNS TABLE (update_active boolean, from_version text, to_version text, started_at timestamptz)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
          SELECT
            count(*) > 0 AND bool_and(source_job_type IS NOT DISTINCT FROM 'deploy'),
            (array_agg(progress ->> 'from_version' ORDER BY created_at))[1],
            (array_agg(COALESCE(progress ->> 'to_version', source_job_id) ORDER BY created_at))[1],
            min(started_at)
          FROM public.maintenance_window
          WHERE kind = 'full' AND state IN ({BLOCKING_STATES})
        $$
    """)  # sql-ok: BLOCKING_STATES ist eine feste Konstante dieser Migration
    op.execute("REVOKE ALL ON FUNCTION public.maintenance_public_update() FROM PUBLIC")
    # Nur die Abgabebox braucht sie; das Backend liest die Tabelle selbst (public_status).
    op.execute("GRANT EXECUTE ON FUNCTION public.maintenance_public_update() TO hocx_abgabebox")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS public.maintenance_public_update()")
