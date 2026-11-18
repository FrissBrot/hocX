"""Dateien bekommen einen Kontext (Plan «Berechtigungen», Phase 2).

``stored_file.context_type`` ∈ {protokoll, abgabe, album, ablage} und ``context_id`` (Protokoll
bzw. Abgabe-Auftrag; bei album/ablage NULL). Gespeichert wird der PRIMÄRE Kontext (Herkunft) nach
Priorität abgabe > protokoll > album > ablage. Eine Datei kann zusätzlich in weiteren Kontexten
verwendet sein (z. B. ein Galerie-Foto im Protokoll) - der Zugriff prüft weiterhin jeden
verknüpften Kontext (additiv, access_service.ensure_can_read_stored_file).

Eine SQL-Funktion ``hocx_file_context(stored_file_id)`` berechnet den Kontext - für den Nachtrag
hier, für die Trigger auf den Verknüpfungstabellen (setzen den Kontext beim Verknüpfen, auch aus
der Abgabebox) und für den Probelauf-Bericht (``app.services.file_context_service.report``).
Ohne Verknüpfung: «ablage».

Reversibel: downgrade entfernt Trigger, Funktion und Spalten (die Zuordnung ist jederzeit aus den
Verknüpfungen neu berechenbar).

Revision ID: 0189_stored_file_context
Revises: 0188_tenant_require_mfa
Create Date: 2026-11-18
"""

from alembic import op

revision = "0189_stored_file_context"
down_revision = "0188_tenant_require_mfa"
branch_labels = None
depends_on = None

CONTEXT_FUNCTION = """
CREATE OR REPLACE FUNCTION public.hocx_file_context(p_file bigint, OUT context_type text, OUT context_id bigint)
LANGUAGE sql STABLE
SET search_path = public, pg_temp
AS $$
    SELECT c.t, c.i FROM (
        SELECT 1 AS prio, 'abgabe'::text AS t, u.assignment_id AS i
          FROM submission_upload_file f JOIN submission_upload u ON u.id = f.upload_id
         WHERE f.stored_file_id = p_file
        UNION ALL
        SELECT 1, 'abgabe', g.submission_assignment_id FROM gallery_image g
         WHERE g.stored_file_id = p_file AND g.submission_assignment_id IS NOT NULL
        UNION ALL
        SELECT 2, 'protokoll', e.protocol_id
          FROM protocol_image pi
          JOIN protocol_element_block b ON b.id = pi.protocol_element_block_id
          JOIN protocol_element e ON e.id = b.protocol_element_id
         WHERE pi.stored_file_id = p_file
        UNION ALL
        SELECT 2, 'protokoll', d.protocol_id FROM document_export d
         WHERE d.stored_file_id = p_file AND d.protocol_id IS NOT NULL
        UNION ALL
        SELECT 2, 'protokoll', w.protocol_id FROM word_import_document w
         WHERE w.stored_file_id = p_file AND w.protocol_id IS NOT NULL
        UNION ALL
        SELECT 3, 'album', NULL::bigint FROM gallery_image g
         WHERE g.stored_file_id = p_file OR g.live_video_stored_file_id = p_file
        UNION ALL
        SELECT 4, 'ablage', NULL::bigint
    ) c
    ORDER BY c.prio, c.i NULLS LAST
    LIMIT 1
$$
"""

# Trigger: beim Verknüpfen den Kontext der Datei neu berechnen (nur nach oben in der Priorität ist
# nicht nötig - die Funktion liefert immer den stärksten aktuellen Kontext).
REFRESH_FUNCTION = """
CREATE OR REPLACE FUNCTION public.hocx_refresh_file_context() RETURNS trigger
LANGUAGE plpgsql
-- Verknüpfungen legen auch hocx_abgabebox und hocx_photo_worker an, die stored_file nicht ändern
-- dürfen: die Funktion setzt mit den Rechten des Eigentümers nur die Kontext-Spalten genau der
-- verknüpften Datei (fester search_path, SECURITY-RULES §2.4).
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    file_id bigint;
BEGIN
    FOREACH file_id IN ARRAY ARRAY[
        CASE WHEN TG_ARGV[0] IS NOT NULL THEN (to_jsonb(NEW) ->> TG_ARGV[0])::bigint END,
        CASE WHEN TG_ARGV[1] IS NOT NULL THEN (to_jsonb(NEW) ->> TG_ARGV[1])::bigint END
    ] LOOP
        IF file_id IS NOT NULL THEN
            UPDATE stored_file s
               SET context_type = c.context_type, context_id = c.context_id
              FROM hocx_file_context(file_id) c
             WHERE s.id = file_id
               AND (s.context_type IS DISTINCT FROM c.context_type OR s.context_id IS DISTINCT FROM c.context_id);
        END IF;
    END LOOP;
    RETURN NEW;
END;
$$
"""

# (Tabelle, Datei-Spalte, zweite Datei-Spalte oder NULL, Spalten, deren Änderung neu berechnet)
LINKS = (
    ("submission_upload_file", "stored_file_id", None, "stored_file_id"),
    ("gallery_image", "stored_file_id", "live_video_stored_file_id", "stored_file_id, live_video_stored_file_id, submission_assignment_id"),
    ("protocol_image", "stored_file_id", None, "stored_file_id, protocol_element_block_id"),
    ("document_export", "stored_file_id", None, "stored_file_id, protocol_id"),
    ("word_import_document", "stored_file_id", None, "stored_file_id, protocol_id"),
)


def upgrade() -> None:
    op.execute("ALTER TABLE public.stored_file ADD COLUMN context_type text")
    op.execute("ALTER TABLE public.stored_file ADD COLUMN context_id bigint")
    op.execute(CONTEXT_FUNCTION)
    op.execute(
        "UPDATE public.stored_file s SET context_type = c.context_type, context_id = c.context_id "
        "FROM public.stored_file s2 CROSS JOIN LATERAL public.hocx_file_context(s2.id) c WHERE s.id = s2.id"
    )
    op.execute("ALTER TABLE public.stored_file ALTER COLUMN context_type SET DEFAULT 'ablage'")
    op.execute("ALTER TABLE public.stored_file ALTER COLUMN context_type SET NOT NULL")
    op.execute(
        "ALTER TABLE public.stored_file ADD CONSTRAINT ck_stored_file_context_type "
        "CHECK (context_type IN ('protokoll', 'abgabe', 'album', 'ablage'))"
    )
    op.execute("CREATE INDEX idx_stored_file_context ON public.stored_file (tenant_id, context_type, context_id)")
    op.execute(REFRESH_FUNCTION)
    for table, column, second, watched in LINKS:
        second_arg = f"'{second}'" if second else "NULL"
        op.execute(
            f"CREATE TRIGGER trg_{table}_file_context AFTER INSERT OR UPDATE OF {watched} ON public.{table} "  # sql-ok: feste Bezeichner
            f"FOR EACH ROW EXECUTE FUNCTION public.hocx_refresh_file_context('{column}', {second_arg})"
        )
    # Laufzeitrollen lesen die Funktion (Bericht); Trigger laufen mit den Rechten des Schreibenden
    op.execute("GRANT EXECUTE ON FUNCTION public.hocx_file_context(bigint) TO hocx_app")


def downgrade() -> None:
    for table, *_ in LINKS:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_file_context ON public.{table}")  # sql-ok: feste Bezeichner
    op.execute("DROP FUNCTION IF EXISTS public.hocx_refresh_file_context()")
    op.execute("DROP FUNCTION IF EXISTS public.hocx_file_context(bigint)")
    op.execute("DROP INDEX IF EXISTS public.idx_stored_file_context")
    op.execute("ALTER TABLE public.stored_file DROP CONSTRAINT IF EXISTS ck_stored_file_context_type")
    op.execute("ALTER TABLE public.stored_file DROP COLUMN IF EXISTS context_id")
    op.execute("ALTER TABLE public.stored_file DROP COLUMN IF EXISTS context_type")
