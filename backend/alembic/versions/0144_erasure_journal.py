"""Löschjournal (Datenschutz-Audit PRIV-010, Umsetzungsplan Paket 4)

Ein Restore aus dem Backup brachte gelöschte Personen, Dateien und Mandanten unbemerkt zurück.
erasure_journal hält fest, *was* gelöscht wurde (Art und public_id, keine Inhalte, keine Namen).
Ein Restore wendet alle Einträge nach dem Sicherungspunkt erneut an, ausser es wird beim Restore
mit Begründung abgeschaltet (app/backup/run_restore.py, app/services/erasure_journal.py).

Plattformtabelle ohne tenant_id-Spalte (nur die public_id des Mandanten) und ohne RLS: geschrieben
wird in jeder Löschung, gelesen nur vom Backup-Worker. Die Laufzeitrolle darf nur anlegen und
lesen; gekürzt wird über erasure_journal_purge (mindestens 400 Tage, länger als jedes Backup).

Revision ID: 0144_erasure_journal
Revises: 0143_audit_log_security
Create Date: 2026-10-21
"""

from alembic import op

revision = "0144_erasure_journal"
down_revision = "0143_audit_log_security"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE erasure_journal (
            id bigserial PRIMARY KEY,
            kind text NOT NULL,
            subject_public_id uuid NOT NULL,
            tenant_public_id uuid,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_erasure_journal_kind CHECK (kind IN (
                'tenant', 'app_user', 'protocol', 'event', 'submission_assignment', 'submission_upload', 'stored_file'
            ))
        )
        """
    )
    op.execute("CREATE INDEX idx_erasure_journal_created ON erasure_journal (created_at)")
    # Default-Privilegien (0064) geben neuen Tabellen alle Rechte - hier ausdrücklich nur anlegen/lesen.
    op.execute("REVOKE ALL ON erasure_journal FROM hocx_app")
    op.execute("GRANT SELECT, INSERT ON erasure_journal TO hocx_app")
    op.execute("GRANT USAGE, SELECT ON SEQUENCE erasure_journal_id_seq TO hocx_app")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.erasure_journal_purge(p_retention_days integer)
        RETURNS bigint
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
        DECLARE
            deleted bigint;
        BEGIN
            IF p_retention_days IS NULL OR p_retention_days < 400 THEN
                RAISE EXCEPTION 'erasure_journal_purge: Frist muss mindestens 400 Tage betragen';
            END IF;
            DELETE FROM public.erasure_journal WHERE created_at < now() - make_interval(days => p_retention_days);
            GET DIAGNOSTICS deleted = ROW_COUNT;
            RETURN deleted;
        END
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION public.erasure_journal_purge(integer) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION public.erasure_journal_purge(integer) TO hocx_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS public.erasure_journal_purge(integer)")
    op.execute("DROP TABLE IF EXISTS erasure_journal")
