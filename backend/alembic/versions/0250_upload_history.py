"""Upload-Verlauf (Plan «Upload-Verlauf» 2026-11-21, hocX 1.6), Phase 1.

- ``upload_job``: ein Upload-Vorgang, so wie ihn die Person erlebt (ein Dialog-Durchgang mit allen
  Paketen und dem Vorab-Abgleich, ein Ablage-Upload, eine Einreichung, ein Datei-Import …).
  Kanal, Bezug, Optionen (ohne GPS-Werte und Browser-Hinweise), Status und denormalisierte Zähler.
- ``upload_job_item``: eine Datei des Vorgangs mit Ergebnis (hochgeladen, Duplikat, Metadaten
  ergänzt, abgelehnt, Virenfund, fehlgeschlagen, verworfen) und Grund.
- ``stored_file.upload_job_id`` (User-Entscheid E-3): Herkunftsvorgang direkt an der Datei - schneller
  Filter ``GET /files?upload_job_id=`` und Anzeige im Foto-Viewer.
- ``gallery_upload_job.upload_job_id``: die technische Ingest-Warteschlange verweist auf den Vorgang.
- ``stored_file.camera_serial_key`` (User-Entscheid E-13): Kürzel der EXIF-Seriennummer als keyed Hash
  je Mandant (services/camera_serial.py), nie die Seriennummer selbst. Unterscheidet in den
  Kameragruppen eines Vorgangs zwei Geräte desselben Modells; mandantenübergreifend nicht vergleichbar.

Mandantentrennung: beide Tabellen mit ``tenant_id`` NOT NULL und RLS ``tenant_isolation`` (wie 0230).
Die Verweise von Item, Datei und Ingest-Auftrag auf den Vorgang laufen über zusammengesetzte
Fremdschlüssel ``(tenant_id, upload_job_id)`` - ein Vorgang eines anderen Mandanten lässt sich damit
auch durch einen Programmfehler nicht anhängen (SECURITY-RULES 2.2).

Aufbewahrung (User-Entscheid E-9): ein Vorgang bleibt, solange mindestens eine seiner Dateien
existiert (auch im Papierkorb), danach wird er sofort gelöscht. Das erledigt der Statement-Trigger
``trg_stored_file_upload_history`` nach dem endgültigen Löschen von Dateien; er leert ausserdem den
Namen von Items, deren Datei endgültig gelöscht wurde (der Name kann ein Personendatum sein).
SECURITY DEFINER mit festem search_path, weil auch Rollen ohne Rechte auf den Verlaufstabellen
Dateien löschen (Mandantenlöschung, Aufräumjobs). Vorgänge, die nie eine Datei hatten (nur Duplikate
oder Ablehnungen), räumt ``retention_service`` nach ``upload_job_retention_days`` ab.

Revision ID: 0250_upload_history
Revises: 0230_cloud_import (vorläufig; bei der Integration neu verketten)
Create Date: 2026-11-22
"""

from __future__ import annotations

from alembic import op

revision = "0250_upload_history"
down_revision = "0230_cloud_import"
branch_labels = None
depends_on = None

SCOPE = "(SELECT public.hocx_rls_tenant())"
BASE = f"({SCOPE} IS NULL OR tenant_id = {SCOPE})"

CHANNELS = (
    "gallery", "document", "protocol_image", "todo", "submission_link", "abgabebox", "word_import", "tenant_import", "cloud_import",
)
ACTOR_KINDS = ("user", "submission_person", "anonymous_link", "platform_admin", "system")
JOB_STATUSES = ("open", "processing", "done", "partial", "failed", "cancelled")
ITEM_STATUSES = ("uploaded", "duplicate", "metadata_updated", "rejected", "infected", "failed", "discarded")


def _in(values: tuple[str, ...]) -> str:
    return "(" + ", ".join(f"'{value}'" for value in values) + ")"


CLEANUP_FUNCTION = """
CREATE OR REPLACE FUNCTION public.hocx_upload_history_after_file_delete() RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
    -- Name endgültig gelöschter Dateien leeren (Status bleibt: «Datei gelöscht»)
    UPDATE upload_job_item i
       SET original_name = NULL
     WHERE i.upload_job_id IN (SELECT DISTINCT o.upload_job_id FROM old_rows o WHERE o.upload_job_id IS NOT NULL)
       AND i.status = 'uploaded'
       AND i.stored_file_id IS NULL
       AND i.original_name IS NOT NULL;
    -- E-9: Vorgang ohne verbleibende Datei sofort entfernen (Items per Kaskade)
    DELETE FROM upload_job j
     WHERE j.id IN (SELECT DISTINCT o.upload_job_id FROM old_rows o WHERE o.upload_job_id IS NOT NULL)
       AND NOT EXISTS (SELECT 1 FROM stored_file s WHERE s.upload_job_id = j.id);
    RETURN NULL;
END;
$$
"""


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE upload_job (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            tenant_id bigint NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            channel text NOT NULL,
            actor_kind text NOT NULL DEFAULT 'user',
            created_by bigint REFERENCES app_user(id) ON DELETE SET NULL,
            actor_ref jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            event_id bigint REFERENCES event(id) ON DELETE SET NULL,
            submission_assignment_id bigint REFERENCES submission_assignment(id) ON DELETE SET NULL,
            submission_element_ref text,
            submission_element_label text,
            cycle_config_id bigint REFERENCES cycle_config(id) ON DELETE SET NULL,
            protocol_id bigint REFERENCES protocol(id) ON DELETE SET NULL,
            protocol_todo_id bigint REFERENCES protocol_todo(id) ON DELETE SET NULL,
            submission_upload_id bigint REFERENCES submission_upload(id) ON DELETE SET NULL,
            import_job_id uuid REFERENCES import_job(id) ON DELETE SET NULL,
            group_day date,
            options jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            status text NOT NULL DEFAULT 'open',
            total integer NOT NULL DEFAULT 0,
            uploaded integer NOT NULL DEFAULT 0,
            duplicates integer NOT NULL DEFAULT 0,
            metadata_updated integer NOT NULL DEFAULT 0,
            rejected integer NOT NULL DEFAULT 0,
            infected integer NOT NULL DEFAULT 0,
            failed integer NOT NULL DEFAULT 0,
            discarded integer NOT NULL DEFAULT 0,
            reconstructed boolean NOT NULL DEFAULT false,
            created_at timestamptz NOT NULL DEFAULT now(),
            client_closed_at timestamptz,
            finished_at timestamptz,
            CONSTRAINT uq_upload_job_tenant_id UNIQUE (tenant_id, id),
            CONSTRAINT ck_upload_job_channel CHECK (channel IN {_in(CHANNELS)}),
            CONSTRAINT ck_upload_job_actor_kind CHECK (actor_kind IN {_in(ACTOR_KINDS)}),
            CONSTRAINT ck_upload_job_status CHECK (status IN {_in(JOB_STATUSES)})
        )
        """  # sql-ok: feste Werte aus dieser Datei
    )
    op.execute("CREATE INDEX idx_upload_job_tenant_created ON upload_job (tenant_id, created_at DESC, id DESC)")
    op.execute("CREATE INDEX idx_upload_job_tenant_creator ON upload_job (tenant_id, created_by, created_at DESC)")
    op.execute("CREATE INDEX idx_upload_job_tenant_channel ON upload_job (tenant_id, channel, created_at DESC)")
    op.execute("CREATE INDEX idx_upload_job_active ON upload_job (created_at) WHERE status IN ('open', 'processing')")
    # Ein Vorgang je Einreichung bzw. Datei-Import (Trigger der Abgabebox, Import-Worker, Backfill)
    op.execute("CREATE UNIQUE INDEX uq_upload_job_submission_upload ON upload_job (submission_upload_id) WHERE submission_upload_id IS NOT NULL")
    op.execute("CREATE UNIQUE INDEX uq_upload_job_import_job ON upload_job (import_job_id) WHERE import_job_id IS NOT NULL")
    # E-6: ein Vorgang je Protokoll und Tag
    op.execute(
        "CREATE UNIQUE INDEX uq_upload_job_protocol_day ON upload_job (protocol_id, group_day) "
        "WHERE channel = 'protocol_image' AND protocol_id IS NOT NULL"
    )

    op.execute(
        f"""
        CREATE TABLE upload_job_item (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            upload_job_id uuid NOT NULL,
            tenant_id bigint NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            position integer NOT NULL DEFAULT 0,
            original_name text,
            size_bytes bigint,
            mime_type text,
            status text NOT NULL,
            reason_code text,
            reason_params jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            source text NOT NULL DEFAULT 'server',
            stored_file_id bigint REFERENCES stored_file(id) ON DELETE SET NULL,
            existing_file_id bigint REFERENCES stored_file(id) ON DELETE SET NULL,
            applied text[] NOT NULL DEFAULT '{{}}',
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT fk_upload_job_item_job FOREIGN KEY (tenant_id, upload_job_id)
                REFERENCES upload_job (tenant_id, id) ON DELETE CASCADE,
            CONSTRAINT ck_upload_job_item_status CHECK (status IN {_in(ITEM_STATUSES)}),
            CONSTRAINT ck_upload_job_item_source CHECK (source IN ('server', 'client'))
        )
        """  # sql-ok: feste Werte aus dieser Datei
    )
    op.execute("CREATE INDEX idx_upload_job_item_job ON upload_job_item (upload_job_id, position, id)")
    op.execute("CREATE INDEX idx_upload_job_item_job_status ON upload_job_item (upload_job_id, status)")
    op.execute("CREATE INDEX idx_upload_job_item_tenant ON upload_job_item (tenant_id)")
    # Eine Datei hat genau einen Herkunftsvorgang
    op.execute("CREATE UNIQUE INDEX uq_upload_job_item_file ON upload_job_item (stored_file_id) WHERE status = 'uploaded' AND stored_file_id IS NOT NULL")
    op.execute("CREATE INDEX idx_upload_job_item_existing ON upload_job_item (tenant_id, existing_file_id) WHERE existing_file_id IS NOT NULL")

    for table in ("upload_job", "upload_job_item"):
        op.execute(f"CREATE POLICY tenant_isolation ON public.{table} FOR ALL USING {BASE} WITH CHECK {BASE}")  # sql-ok: feste Policy und Tabellennamen
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")  # sql-ok: fester Tabellenname

    # E-3: Herkunft direkt an der Datei. ON DELETE SET NULL nur für upload_job_id (tenant_id bleibt).
    op.execute("ALTER TABLE stored_file ADD COLUMN upload_job_id uuid")
    op.execute(
        "ALTER TABLE stored_file ADD CONSTRAINT fk_stored_file_upload_job FOREIGN KEY (tenant_id, upload_job_id) "
        "REFERENCES upload_job (tenant_id, id) ON DELETE SET NULL (upload_job_id)"
    )
    op.execute("CREATE INDEX idx_stored_file_upload_job ON stored_file (upload_job_id) WHERE upload_job_id IS NOT NULL")
    op.execute("ALTER TABLE stored_file ADD COLUMN camera_serial_key text")

    op.execute("ALTER TABLE gallery_upload_job ADD COLUMN upload_job_id uuid")
    op.execute(
        "ALTER TABLE gallery_upload_job ADD CONSTRAINT fk_gallery_upload_job_upload_job FOREIGN KEY (tenant_id, upload_job_id) "
        "REFERENCES upload_job (tenant_id, id) ON DELETE SET NULL (upload_job_id)"
    )
    op.execute("CREATE INDEX idx_gallery_upload_job_upload_job ON gallery_upload_job (upload_job_id) WHERE upload_job_id IS NOT NULL")

    op.execute(CLEANUP_FUNCTION)
    op.execute("REVOKE ALL ON FUNCTION public.hocx_upload_history_after_file_delete() FROM PUBLIC")
    op.execute(
        "CREATE TRIGGER trg_stored_file_upload_history AFTER DELETE ON stored_file "
        "REFERENCING OLD TABLE AS old_rows FOR EACH STATEMENT EXECUTE FUNCTION public.hocx_upload_history_after_file_delete()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_stored_file_upload_history ON stored_file")
    op.execute("DROP FUNCTION IF EXISTS public.hocx_upload_history_after_file_delete()")
    op.execute("ALTER TABLE gallery_upload_job DROP COLUMN IF EXISTS upload_job_id")
    op.execute("ALTER TABLE stored_file DROP COLUMN IF EXISTS camera_serial_key")
    op.execute("ALTER TABLE stored_file DROP COLUMN IF EXISTS upload_job_id")
    op.execute("DROP TABLE IF EXISTS upload_job_item")
    op.execute("DROP TABLE IF EXISTS upload_job")
