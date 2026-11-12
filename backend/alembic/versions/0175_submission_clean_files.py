"""Abgabe-Pendenzen nur mit geprüften Dateien erledigen; App-Dateien in der Abgabebox mitzählen.

1. ``trg_sync_todo_status`` hing an ``submission_upload`` und erledigte die Pendenz beim Einfügen
   der Einreichung, also bevor ihre Dateien existierten. Eine Datei in Quarantäne (Virenscanner
   nicht erreichbar) erledigte die Pendenz deshalb sofort, und die Mail «Abgabe eingegangen» ging
   raus, auch wenn die Datei später als infiziert galt. Neu hängt der Trigger an
   ``submission_upload_file`` und erledigt nur, wenn die Datei sauber geprüft ist. Dateien, die erst
   der erneute Scan freigibt, erledigt der Abgleich (``submission_service.rescan_pending`` und der
   Job ``submission_todo_sync``). Als Erledigt-Zeitpunkt gilt die Einreichung (``submitted_at``),
   nicht der Zeitpunkt des Triggers. Der Zweig für den Status ``reopened`` fällt weg: diesen Status
   schreibt niemand mehr (``reopen_element`` legt eine ``submitted``-Zeile an).

2. ``submission_linked_file_counts(assignment_id)``: Anzahl der Dateien je Element, die in der App
   direkt mit einem Element der Abgabe verknüpft sind (``gallery_image``). Die Abgabebox darf
   ``gallery_image`` nicht lesen, zählte diese Dateien deshalb nicht zur Höchstzahl je Element und
   liess mehr Dateien zu als die App. Die Funktion liefert nur Zahlen je Element und nur für den
   Mandanten des gesetzten Upload-Links (``hocx_rls_abgabebox_tenant``).

Revision ID: 0175_submission_clean_files
Revises: 0174_umlaut_session_label
Create Date: 2026-11-12
"""

from alembic import op

revision = "0175_submission_clean_files"
down_revision = "0174_umlaut_session_label"
branch_labels = None
depends_on = None

_DONE = 3

_FUNCTION = f"""
CREATE OR REPLACE FUNCTION public.sync_todo_status_on_submission_file() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public
    AS $$
        DECLARE
            v_upload submission_upload%ROWTYPE;
            v_refs TEXT[];
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM stored_file sf WHERE sf.id = NEW.stored_file_id AND sf.scan_status = 'clean'
            ) THEN
                RETURN NEW;
            END IF;
            SELECT * INTO v_upload FROM submission_upload u WHERE u.id = NEW.upload_id;
            IF NOT FOUND OR v_upload.status <> 'submitted' OR v_upload.submitted_at IS NULL THEN
                RETURN NEW;
            END IF;

            IF v_upload.event_id IS NOT NULL THEN
                SELECT ARRAY['event-' || e.public_id::TEXT, 'event-' || e.id::TEXT]
                  INTO v_refs FROM event e WHERE e.id = v_upload.event_id;
            ELSIF v_upload.list_entry_id IS NOT NULL THEN
                SELECT ARRAY['entry-' || le.public_id::TEXT, 'entry-' || le.id::TEXT]
                  INTO v_refs FROM list_entry le WHERE le.id = v_upload.list_entry_id;
            ELSE
                v_refs := ARRAY['manual'];
            END IF;
            IF v_refs IS NULL THEN
                RETURN NEW;
            END IF;

            UPDATE protocol_todo
            SET todo_status_id = {_DONE},
                completed_at = v_upload.submitted_at
            WHERE submission_assignment_id = v_upload.assignment_id
              AND element_ref = ANY(v_refs)
              AND todo_status_id <> {_DONE};
            RETURN NEW;
        END;
    $$;
"""  # sql-ok: nur feste Status-IDs aus diesem Modul

_LINKED_FILES = """
CREATE OR REPLACE FUNCTION public.submission_linked_file_counts(p_assignment_id BIGINT)
RETURNS TABLE (event_id BIGINT, list_entry_id BIGINT, file_count INTEGER)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
    AS $$
        SELECT e.id, le.id, COUNT(*)::INTEGER
        FROM gallery_image g
        JOIN submission_assignment a ON a.id = g.submission_assignment_id AND a.tenant_id = g.tenant_id
        LEFT JOIN event e
          ON g.submission_element_ref = 'event-' || e.public_id::TEXT AND e.tenant_id = a.tenant_id
        LEFT JOIN list_entry le
          ON g.submission_element_ref = 'entry-' || le.public_id::TEXT AND le.list_definition_id = a.list_definition_id
        WHERE g.submission_assignment_id = p_assignment_id
          -- nur der Mandant des gesetzten Upload-Links (wie die RLS der Abgabebox, 0133)
          AND a.tenant_id = (SELECT public.hocx_rls_abgabebox_tenant())
          AND (e.id IS NOT NULL OR le.id IS NOT NULL OR g.submission_element_ref = 'manual')
        GROUP BY e.id, le.id
    $$;
"""

_OLD_FUNCTION = f"""
CREATE OR REPLACE FUNCTION public.sync_todo_status_on_submission_upload() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public
    AS $$
        DECLARE
            v_refs TEXT[];
        BEGIN
            IF NEW.event_id IS NOT NULL THEN
                SELECT ARRAY['event-' || e.public_id::TEXT, 'event-' || e.id::TEXT]
                  INTO v_refs FROM event e WHERE e.id = NEW.event_id;
            ELSIF NEW.list_entry_id IS NOT NULL THEN
                SELECT ARRAY['entry-' || le.public_id::TEXT, 'entry-' || le.id::TEXT]
                  INTO v_refs FROM list_entry le WHERE le.id = NEW.list_entry_id;
            ELSE
                v_refs := ARRAY['manual'];
            END IF;
            IF v_refs IS NULL THEN
                RETURN NEW;
            END IF;
            IF NEW.status = 'submitted' AND NEW.submitted_at IS NOT NULL THEN
                UPDATE protocol_todo
                SET todo_status_id = {_DONE},
                    completed_at = NOW()
                WHERE submission_assignment_id = NEW.assignment_id
                  AND element_ref = ANY(v_refs)
                  AND todo_status_id <> {_DONE};
            END IF;
            RETURN NEW;
        END;
    $$;
"""  # sql-ok: nur feste Status-IDs aus diesem Modul


def upgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_sync_todo_status ON submission_upload")
    op.execute("DROP FUNCTION IF EXISTS public.sync_todo_status_on_submission_upload()")
    op.execute(_FUNCTION)
    op.execute(
        "CREATE TRIGGER trg_sync_todo_status AFTER INSERT ON submission_upload_file "
        "FOR EACH ROW EXECUTE FUNCTION public.sync_todo_status_on_submission_file()"
    )
    op.execute(_LINKED_FILES)
    op.execute("REVOKE ALL ON FUNCTION public.submission_linked_file_counts(BIGINT) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION public.submission_linked_file_counts(BIGINT) TO hocx_abgabebox")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS public.submission_linked_file_counts(BIGINT)")
    op.execute("DROP TRIGGER IF EXISTS trg_sync_todo_status ON submission_upload_file")
    op.execute("DROP FUNCTION IF EXISTS public.sync_todo_status_on_submission_file()")
    op.execute(_OLD_FUNCTION)
    op.execute(
        "CREATE TRIGGER trg_sync_todo_status AFTER INSERT ON submission_upload "
        "FOR EACH ROW EXECUTE FUNCTION public.sync_todo_status_on_submission_upload()"
    )
