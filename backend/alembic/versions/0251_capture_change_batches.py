"""Rückgängig für Datumskorrekturen (Plan «Upload-Verlauf» 7.5, hocX 1.6).

- ``capture_change_batch``: eine Korrektur (Setzen, Verschieben, Zurücksetzen) über die
  Mehrfachauswahl - auch wenn der Browser sie in Stücke zu 500 Fotos teilt (die Stücke tragen die
  batch_id des ersten). Parameter, Bezug zum Upload-Vorgang, Rückgängig-Zeitpunkt.
- ``capture_change_item``: je tatsächlich geänderter Datei vorheriger und neuer Korrekturwert.
  Rückgängig setzt nur Fotos zurück, deren aktueller Wert noch dem neuen entspricht.

Aufbewahrung (User-Entscheid E-9): an die Dateien gebunden - ein Item verschwindet mit seiner Datei
(CASCADE), eine Korrektur ohne verbleibende Items löscht der Trigger nach dem endgültigen Löschen
von Dateien (Funktion aus 0250 erweitert). Kein Fristablauf.

Beide Tabellen: ``tenant_id`` NOT NULL, RLS ``tenant_isolation``; Items hängen über
(tenant_id, batch_id) an einer Korrektur desselben Mandanten.

Revision ID: 0251_capture_change_batches
Revises: 0250_upload_history
Create Date: 2026-11-22
"""

from __future__ import annotations

from alembic import op

revision = "0251_capture_change_batches"
down_revision = "0250_upload_history"
branch_labels = None
depends_on = None

SCOPE = "(SELECT public.hocx_rls_tenant())"
BASE = f"({SCOPE} IS NULL OR tenant_id = {SCOPE})"

CLEANUP_FUNCTION = """
CREATE OR REPLACE FUNCTION public.hocx_upload_history_after_file_delete() RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
    UPDATE upload_job_item i
       SET original_name = NULL
     WHERE i.upload_job_id IN (SELECT DISTINCT o.upload_job_id FROM old_rows o WHERE o.upload_job_id IS NOT NULL)
       AND i.status = 'uploaded'
       AND i.stored_file_id IS NULL
       AND i.original_name IS NOT NULL;
    DELETE FROM upload_job j
     WHERE j.id IN (SELECT DISTINCT o.upload_job_id FROM old_rows o WHERE o.upload_job_id IS NOT NULL)
       AND NOT EXISTS (SELECT 1 FROM stored_file s WHERE s.upload_job_id = j.id);
    -- E-9: Rückgängig hängt an den Dateien - Korrekturen ohne verbleibende Datei entfernen
    DELETE FROM capture_change_batch b
     WHERE b.tenant_id IN (SELECT DISTINCT o.tenant_id FROM old_rows o)
       AND NOT EXISTS (SELECT 1 FROM capture_change_item i WHERE i.batch_id = b.id);
    RETURN NULL;
END;
$$
"""

PREVIOUS_FUNCTION = """
CREATE OR REPLACE FUNCTION public.hocx_upload_history_after_file_delete() RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
    UPDATE upload_job_item i
       SET original_name = NULL
     WHERE i.upload_job_id IN (SELECT DISTINCT o.upload_job_id FROM old_rows o WHERE o.upload_job_id IS NOT NULL)
       AND i.status = 'uploaded'
       AND i.stored_file_id IS NULL
       AND i.original_name IS NOT NULL;
    DELETE FROM upload_job j
     WHERE j.id IN (SELECT DISTINCT o.upload_job_id FROM old_rows o WHERE o.upload_job_id IS NOT NULL)
       AND NOT EXISTS (SELECT 1 FROM stored_file s WHERE s.upload_job_id = j.id);
    RETURN NULL;
END;
$$
"""


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE capture_change_batch (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            tenant_id bigint NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            created_by bigint REFERENCES app_user(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            mode text NOT NULL,
            params jsonb NOT NULL DEFAULT '{}'::jsonb,
            upload_job_id uuid,
            updated_count integer NOT NULL DEFAULT 0,
            undone_at timestamptz,
            undone_by bigint REFERENCES app_user(id) ON DELETE SET NULL,
            CONSTRAINT uq_capture_change_batch_tenant_id UNIQUE (tenant_id, id),
            CONSTRAINT ck_capture_change_batch_mode CHECK (mode IN ('set', 'shift', 'reset')),
            CONSTRAINT fk_capture_change_batch_upload_job FOREIGN KEY (tenant_id, upload_job_id)
                REFERENCES upload_job (tenant_id, id) ON DELETE SET NULL (upload_job_id)
        )
        """
    )
    op.execute("CREATE INDEX idx_capture_change_batch_tenant ON capture_change_batch (tenant_id, created_at DESC)")
    op.execute("CREATE INDEX idx_capture_change_batch_job ON capture_change_batch (upload_job_id) WHERE upload_job_id IS NOT NULL")
    op.execute(
        """
        CREATE TABLE capture_change_item (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            batch_id uuid NOT NULL,
            tenant_id bigint NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            stored_file_id bigint NOT NULL REFERENCES stored_file(id) ON DELETE CASCADE,
            prev_corrected_at timestamptz,
            prev_has_time boolean NOT NULL DEFAULT false,
            new_corrected_at timestamptz,
            new_has_time boolean NOT NULL DEFAULT false,
            CONSTRAINT fk_capture_change_item_batch FOREIGN KEY (tenant_id, batch_id)
                REFERENCES capture_change_batch (tenant_id, id) ON DELETE CASCADE,
            CONSTRAINT uq_capture_change_item_file UNIQUE (batch_id, stored_file_id)
        )
        """
    )
    op.execute("CREATE INDEX idx_capture_change_item_file ON capture_change_item (stored_file_id)")
    op.execute("CREATE INDEX idx_capture_change_item_tenant ON capture_change_item (tenant_id)")
    for table in ("capture_change_batch", "capture_change_item"):
        op.execute(f"CREATE POLICY tenant_isolation ON public.{table} FOR ALL USING {BASE} WITH CHECK {BASE}")  # sql-ok: feste Policy und Tabellennamen
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")  # sql-ok: fester Tabellenname
    op.execute(CLEANUP_FUNCTION)


def downgrade() -> None:
    op.execute(PREVIOUS_FUNCTION)
    op.execute("DROP TABLE IF EXISTS capture_change_item")
    op.execute("DROP TABLE IF EXISTS capture_change_batch")
