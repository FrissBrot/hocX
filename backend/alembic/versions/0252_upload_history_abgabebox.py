"""Upload-Verlauf: Einreichungen der Abgabebox per DB-Trigger (User-Entscheid E-5, hocX 1.6).

Die Abgabebox schreibt mit ihrer eingeschränkten Rolle ``hocx_abgabebox`` nur INSERTs in
submission_upload, stored_file und submission_upload_file - sie bekommt keine neuen Rechte und ihr
Code bleibt unverändert. Der Trigger ``trg_submission_upload_file_history`` legt nach jedem
INSERT in submission_upload_file:

- je Einreichung (submission_upload) einen Vorgang ``abgabebox`` an (eindeutig über
  submission_upload_id; actor_kind ``anonymous_link``, keine Person, kein Konto),
- ein Item ``uploaded`` für die Datei an und
- trägt ``stored_file.upload_job_id`` ein (E-3).

Die Funktion läuft als SECURITY DEFINER mit festem search_path (SECURITY-RULES 2.4) und schreibt
nur Zeilen, die sich aus der neuen Verknüpfung ergeben; Mandant ist der der Datei, geprüft gegen
den Mandanten der Abgabe (stimmen sie nicht überein, entsteht kein Verlaufseintrag). Abgelehnte
Dateien und Virenfunde der Abgabebox erscheinen nicht - sie gelangen nie in die Datenbank, und
Duplikate meldet die Abgabebox absichtlich nicht.

Revision ID: 0252_upload_history_abgabebox
Revises: 0251_capture_change_batches
Create Date: 2026-11-22
"""

from __future__ import annotations

from alembic import op

revision = "0252_upload_history_abgabebox"
down_revision = "0251_capture_change_batches"
branch_labels = None
depends_on = None

FUNCTION = """
CREATE OR REPLACE FUNCTION public.hocx_upload_history_abgabebox() RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_file_tenant bigint;
    v_name text;
    v_size bigint;
    v_mime text;
    v_assignment bigint;
    v_assignment_tenant bigint;
    v_event bigint;
    v_job uuid;
    v_inserted integer;
BEGIN
    SELECT s.tenant_id, s.original_name, s.file_size_bytes, s.mime_type
      INTO v_file_tenant, v_name, v_size, v_mime
      FROM stored_file s WHERE s.id = NEW.stored_file_id;
    SELECT u.assignment_id, u.event_id INTO v_assignment, v_event FROM submission_upload u WHERE u.id = NEW.upload_id;
    SELECT a.tenant_id INTO v_assignment_tenant FROM submission_assignment a WHERE a.id = v_assignment;
    IF v_file_tenant IS NULL OR v_assignment_tenant IS DISTINCT FROM v_file_tenant THEN
        RETURN NEW;
    END IF;

    INSERT INTO upload_job (tenant_id, channel, actor_kind, submission_upload_id, submission_assignment_id, event_id,
                            status, client_closed_at, finished_at)
    VALUES (v_file_tenant, 'abgabebox', 'anonymous_link', NEW.upload_id, v_assignment, v_event, 'done', now(), now())
    ON CONFLICT (submission_upload_id) WHERE submission_upload_id IS NOT NULL DO NOTHING;
    SELECT j.id INTO v_job FROM upload_job j WHERE j.submission_upload_id = NEW.upload_id AND j.tenant_id = v_file_tenant;
    IF v_job IS NULL THEN
        RETURN NEW;
    END IF;

    INSERT INTO upload_job_item (upload_job_id, tenant_id, position, original_name, size_bytes, mime_type, status, stored_file_id)
    VALUES (v_job, v_file_tenant, NEW.sort_index, left(v_name, 255), v_size, v_mime, 'uploaded', NEW.stored_file_id)
    ON CONFLICT DO NOTHING;
    GET DIAGNOSTICS v_inserted = ROW_COUNT;
    IF v_inserted > 0 THEN
        UPDATE upload_job SET total = total + 1, uploaded = uploaded + 1, finished_at = now() WHERE id = v_job;
    END IF;
    UPDATE stored_file SET upload_job_id = v_job WHERE id = NEW.stored_file_id AND upload_job_id IS NULL;
    RETURN NEW;
END;
$$
"""


def upgrade() -> None:
    op.execute(FUNCTION)
    op.execute("REVOKE ALL ON FUNCTION public.hocx_upload_history_abgabebox() FROM PUBLIC")
    op.execute(
        "CREATE TRIGGER trg_submission_upload_file_history AFTER INSERT ON submission_upload_file "
        "FOR EACH ROW EXECUTE FUNCTION public.hocx_upload_history_abgabebox()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_submission_upload_file_history ON submission_upload_file")
    op.execute("DROP FUNCTION IF EXISTS public.hocx_upload_history_abgabebox()")
