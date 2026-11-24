"""Upload-Verlauf: abgelehnte und doppelte Dateien der Abgabebox als Zeilen im Vorgang (hocX 1.6).

Die Abgabebox (eigener Dienst, Rolle ``hocx_abgabebox`` mit nur INSERT auf submission_upload_log)
bekommt keine neuen Rechte (User-Entscheid E-5). Sie schreibt je abgelehnter oder doppelter Datei
eine Zeile ``file_rejected``/``file_duplicate`` in ``submission_upload_log`` mit den neuen Spalten

- ``request_ref`` (zufällige UUID je Anfrage - fasst die Zeilen einer Anfrage zu einem Vorgang),
- ``upload_id`` (die gespeicherte Einreichung, wenn die Anfrage trotzdem Dateien gespeichert hat),
- ``reason_code``, ``file_name``, ``file_size``.

Der Trigger ``trg_submission_upload_log_history`` (BEFORE INSERT, SECURITY DEFINER, fester search_path;
leert danach Name und Grösse in der Log-Zeile, entfernt Steuerzeichen, höchstens 50 Vorgänge aus
abgelehnten Anfragen je Abgabe und Stunde) macht daraus
eine Zeile im Vorgang ``abgabebox``: bei ``upload_id`` im Vorgang dieser Einreichung (nur wenn sie zur
selben Abgabe gehört), sonst in einem Vorgang je Anfrage (``upload_job.request_ref``, eindeutig je
Mandant). Mandant ist immer der der Abgabe; unbekannte Gründe werden ignoriert. Zähler und Status des
Vorgangs werden nachgeführt. Vorgänge ohne Datei räumt ``retention_service`` wie bisher nach 30 Tagen ab.

Die neuen Log-Spalten stehen bewusst nicht im ORM-Modell des Backends: Klon, Import und Export
übernehmen sie nicht (der Verlauf wird nie kopiert), und das Abgabe-Protokoll blendet die
Datei-Zeilen aus (submission_repository.list_upload_log).

Revision ID: 0254_upload_rejections
Revises: 0253_camera_serial_backfill
Create Date: 2026-11-23
"""

from __future__ import annotations

from alembic import op

revision = "0254_upload_rejections"
down_revision = "0253_camera_serial_backfill"
branch_labels = None
depends_on = None

FUNCTION = """
CREATE OR REPLACE FUNCTION public.hocx_upload_history_abgabebox_file_log() RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_tenant bigint;
    v_job uuid;
    v_status text;
    v_position integer;
    v_name text;
    v_size bigint := NEW.file_size;
BEGIN
    IF NEW.reason_code IS NULL OR NEW.reason_code NOT IN ('too_large', 'unsupported_format', 'rule_violation', 'quota_exceeded',
                               'infected', 'scan_failed', 'duplicate_exact') THEN
        NEW.file_name := NULL;
        NEW.file_size := NULL;
        RETURN NEW;
    END IF;
    -- Steuer- und Bidi-Zeichen entfernen (Security-Review N-2), Name nur im Vorgang behalten
    v_name := left(regexp_replace(NEW.file_name, '[[:cntrl:]\u200e\u200f\u202a-\u202e\u2066-\u2069]', '', 'g'), 255);
    -- Datensparsamkeit (N-1): Name und Grösse bleiben nicht im Abgabe-Protokoll stehen
    NEW.file_name := NULL;
    NEW.file_size := NULL;
    SELECT a.tenant_id INTO v_tenant FROM submission_assignment a WHERE a.id = NEW.assignment_id;
    IF v_tenant IS NULL THEN
        RETURN NEW;
    END IF;

    IF NEW.upload_id IS NOT NULL THEN
        -- Nur der Vorgang einer Einreichung derselben Abgabe und desselben Mandanten
        SELECT j.id INTO v_job
          FROM upload_job j
          JOIN submission_upload u ON u.id = j.submission_upload_id
         WHERE j.submission_upload_id = NEW.upload_id
           AND u.assignment_id = NEW.assignment_id
           AND j.tenant_id = v_tenant;
    END IF;
    IF v_job IS NULL AND NEW.request_ref IS NOT NULL THEN
        -- Mengenbremse je Abgabe (Security-Review M-1): höchstens 50 abgelehnte Anfragen je Stunde
        -- werden zu Vorgängen, danach bleibt nur das Abgabe-Protokoll.
        IF NOT EXISTS (SELECT 1 FROM upload_job j WHERE j.tenant_id = v_tenant AND j.request_ref = NEW.request_ref)
           AND (SELECT count(*) FROM upload_job j
                 WHERE j.tenant_id = v_tenant AND j.channel = 'abgabebox' AND j.request_ref IS NOT NULL
                   AND j.submission_assignment_id = NEW.assignment_id AND j.created_at > now() - interval '1 hour') >= 50 THEN
            RETURN NEW;
        END IF;
        INSERT INTO upload_job (tenant_id, channel, actor_kind, submission_assignment_id, submission_element_ref,
                                request_ref, status, client_closed_at, finished_at)
        VALUES (v_tenant, 'abgabebox', 'anonymous_link', NEW.assignment_id, NEW.element_ref,
                NEW.request_ref, 'done', now(), now())
        ON CONFLICT (tenant_id, request_ref) WHERE request_ref IS NOT NULL DO NOTHING;
        SELECT j.id INTO v_job
          FROM upload_job j
         WHERE j.tenant_id = v_tenant
           AND j.request_ref = NEW.request_ref
           AND j.channel = 'abgabebox'
           AND j.submission_assignment_id = NEW.assignment_id;
    END IF;
    IF v_job IS NULL THEN
        RETURN NEW;
    END IF;

    v_status := CASE NEW.reason_code
        WHEN 'infected' THEN 'infected'
        WHEN 'duplicate_exact' THEN 'duplicate'
        WHEN 'scan_failed' THEN 'failed'
        ELSE 'rejected'
    END;
    SELECT j.total INTO v_position FROM upload_job j WHERE j.id = v_job FOR UPDATE;
    INSERT INTO upload_job_item (upload_job_id, tenant_id, position, original_name, size_bytes, status, reason_code, source)
    VALUES (v_job, v_tenant, COALESCE(v_position, 0), NULLIF(v_name, ''),
            CASE WHEN v_size >= 0 THEN v_size END, v_status,
            CASE WHEN NEW.reason_code = 'duplicate_exact' THEN 'duplicate_exact' ELSE NEW.reason_code END, 'server');
    UPDATE upload_job
       SET total = total + 1,
           duplicates = duplicates + (v_status = 'duplicate')::int,
           rejected = rejected + (v_status = 'rejected')::int,
           infected = infected + (v_status = 'infected')::int,
           failed = failed + (v_status = 'failed')::int,
           finished_at = now()
     WHERE id = v_job;
    UPDATE upload_job
       SET status = CASE
               WHEN rejected + infected + failed = 0 THEN 'done'
               WHEN uploaded + duplicates + metadata_updated > 0 THEN 'partial'
               ELSE 'failed'
           END
     WHERE id = v_job;
    RETURN NEW;
END;
$$
"""


def upgrade() -> None:
    op.execute("ALTER TABLE upload_job ADD COLUMN request_ref uuid")
    op.execute("CREATE UNIQUE INDEX uq_upload_job_request_ref ON upload_job (tenant_id, request_ref) WHERE request_ref IS NOT NULL")
    op.execute(
        """
        ALTER TABLE submission_upload_log
            ADD COLUMN request_ref uuid,
            ADD COLUMN upload_id bigint,
            ADD COLUMN reason_code text,
            ADD COLUMN file_name text,
            ADD COLUMN file_size bigint
        """
    )
    op.execute(FUNCTION)
    op.execute("REVOKE ALL ON FUNCTION public.hocx_upload_history_abgabebox_file_log() FROM PUBLIC")
    op.execute(
        # BEFORE: der Trigger leert Name und Grösse in der Log-Zeile selbst; scheitert das INSERT an
        # der RLS-Prüfung der Abgabebox, wird mit der Anweisung auch der Verlaufseintrag zurückgerollt.
        "CREATE TRIGGER trg_submission_upload_log_history BEFORE INSERT ON submission_upload_log "
        "FOR EACH ROW WHEN (NEW.reason_code IS NOT NULL) EXECUTE FUNCTION public.hocx_upload_history_abgabebox_file_log()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_submission_upload_log_history ON submission_upload_log")
    op.execute("DROP FUNCTION IF EXISTS public.hocx_upload_history_abgabebox_file_log()")
    op.execute(
        """
        ALTER TABLE submission_upload_log
            DROP COLUMN IF EXISTS request_ref,
            DROP COLUMN IF EXISTS upload_id,
            DROP COLUMN IF EXISTS reason_code,
            DROP COLUMN IF EXISTS file_name,
            DROP COLUMN IF EXISTS file_size
        """
    )
    op.execute("DROP INDEX IF EXISTS uq_upload_job_request_ref")
    op.execute("ALTER TABLE upload_job DROP COLUMN IF EXISTS request_ref")
