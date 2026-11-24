"""Datei-Import P0 (Plan «Cloud-Datei-Importer» 2026-11-21, hocX 1.6).

- ``import_job``: Import-Vorgang (Quelle ZIP/Takeout oder Ordner-Upload, Regeln, Status, Lease).
  Höchstens ein laufender/vorbereiteter Auftrag je Mandant (Partial Unique Index, User-Entscheid E-5).
- ``import_item``: eine Quelldatei mit Regel-Ergebnis, Ablaufstatus und Verweis auf die importierte
  Datei (``stored_file_id``, SET NULL beim endgültigen Löschen - daran hängt die Aufbewahrung des
  Berichts, E-12).
- Beide Tabellen: ``tenant_id`` NOT NULL, RLS ``tenant_isolation`` wie 0217.
- ``hocx_analyze_upload_tables()`` (SECURITY DEFINER): ANALYZE von stored_file, gallery_image und
  photo_search_doc nach grossen Importen, aufrufbar durch hocx_app.
- Neue Berechtigung ``files.import`` («Dateien importieren»). Standard nur die Rolle «admin»
  (E-8): sie hat ``all_permissions`` und erhält das Recht automatisch, auch für neue Mandanten -
  ``hocx_seed_tenant_roles`` bleibt deshalb unverändert (wie 0207).

Revision ID: 0230_cloud_import
Revises: 0219_password_breach_check
Create Date: 2026-11-22
"""

from __future__ import annotations

from alembic import op

revision = "0230_cloud_import"
down_revision = "0219_password_breach_check"
branch_labels = None
depends_on = None

SCOPE = "(SELECT public.hocx_rls_tenant())"
BASE = f"({SCOPE} IS NULL OR tenant_id = {SCOPE})"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE import_job (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            tenant_id bigint NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            requested_by bigint REFERENCES app_user(id) ON DELETE SET NULL,
            source text NOT NULL,
            status text NOT NULL DEFAULT 'draft',
            type_filter text NOT NULL DEFAULT 'all',
            include_gps boolean NOT NULL DEFAULT true,
            folder_tags boolean NOT NULL DEFAULT false,
            albums_enabled boolean NOT NULL DEFAULT false,
            takeout boolean NOT NULL DEFAULT false,
            rules jsonb NOT NULL DEFAULT '[]'::jsonb,
            archives jsonb NOT NULL DEFAULT '[]'::jsonb,
            album_map jsonb NOT NULL DEFAULT '{}'::jsonb,
            album_report jsonb NOT NULL DEFAULT '{}'::jsonb,
            total_items integer NOT NULL DEFAULT 0,
            total_bytes bigint NOT NULL DEFAULT 0,
            error text,
            lease_owner text,
            lease_until timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            started_at timestamptz,
            served_at timestamptz,
            last_progress_at timestamptz,
            finished_at timestamptz,
            CONSTRAINT ck_import_job_status CHECK (
                status IN ('draft', 'ready', 'queued', 'running', 'cancel_requested', 'cancelled', 'done', 'failed')
            ),
            CONSTRAINT ck_import_job_source CHECK (source IN ('zip', 'folder')),
            CONSTRAINT ck_import_job_type_filter CHECK (type_filter IN ('all', 'images', 'documents')),
            -- Ziel des zusammengesetzten Fremdschlüssels von import_item/upload_job: die Datenbank
            -- garantiert so, dass Einträge im Mandanten ihres Auftrags liegen
            CONSTRAINT uq_import_job_tenant_id UNIQUE (tenant_id, id)
        )
        """
    )
    op.execute("CREATE INDEX idx_import_job_tenant ON import_job (tenant_id, created_at DESC)")
    op.execute("CREATE INDEX idx_import_job_status_lease ON import_job (status, lease_until)")
    op.execute(
        "CREATE UNIQUE INDEX uq_import_job_one_active ON import_job (tenant_id) "
        "WHERE status IN ('draft', 'ready', 'queued', 'running', 'cancel_requested')"
    )

    op.execute(
        """
        CREATE TABLE import_item (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            tenant_id bigint NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            job_id uuid NOT NULL,
            path text NOT NULL,
            size_bytes bigint NOT NULL DEFAULT 0,
            modified_at timestamptz,
            archive_index smallint,
            entry_index integer,
            kind text NOT NULL,
            listing_code text,
            status text NOT NULL DEFAULT 'listed',
            result_code text,
            tags jsonb NOT NULL DEFAULT '[]'::jsonb,
            estimated_date date,
            date_source text,
            hint_date date,
            albums jsonb NOT NULL DEFAULT '[]'::jsonb,
            matched_rules jsonb NOT NULL DEFAULT '[]'::jsonb,
            conflict boolean NOT NULL DEFAULT false,
            group_key text,
            staged_path text,
            stored_file_id bigint REFERENCES stored_file(id) ON DELETE SET NULL,
            existing_file_id bigint REFERENCES stored_file(id) ON DELETE SET NULL,
            attempts smallint NOT NULL DEFAULT 0,
            CONSTRAINT uq_import_item_job_path UNIQUE (job_id, path),
            CONSTRAINT fk_import_item_job FOREIGN KEY (tenant_id, job_id)
                REFERENCES import_job (tenant_id, id) ON DELETE CASCADE,
            CONSTRAINT ck_import_item_status CHECK (
                status IN ('listed', 'queued', 'staged', 'imported', 'duplicate', 'skipped', 'failed', 'cancelled')
            ),
            CONSTRAINT ck_import_item_kind CHECK (kind IN ('image', 'document', 'other'))
        )
        """
    )
    op.execute("CREATE INDEX idx_import_item_job_status ON import_item (job_id, status, id)")
    op.execute("CREATE INDEX idx_import_item_tenant ON import_item (tenant_id)")
    op.execute("CREATE INDEX idx_import_item_stored_file ON import_item (stored_file_id) WHERE stored_file_id IS NOT NULL")
    op.execute("CREATE INDEX idx_import_item_existing_file ON import_item (existing_file_id) WHERE existing_file_id IS NOT NULL")

    for table in ("import_job", "import_item"):
        op.execute(f"CREATE POLICY tenant_isolation ON public.{table} FOR ALL USING {BASE} WITH CHECK {BASE}")  # sql-ok: feste Policy und Tabellennamen
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")  # sql-ok: fester Tabellenname

    op.execute("INSERT INTO permission (key) VALUES ('files.import') ON CONFLICT DO NOTHING")

    # Statistik nach Massenimport (Hinweis aus fix/search-perf-1.5.1): ohne ANALYZE schätzt Postgres
    # bis zum nächsten Autoanalyze ~1 Zeile je Mandant → Nested-Loop-Pläne mit Minuten Laufzeit in
    # Fotoliste und Suche. Die Laufzeitrolle besitzt die Tabellen nicht; diese Funktion erlaubt ihr
    # genau dieses ANALYZE (fester search_path, keine Parameter, sonst keine Rechte).
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.hocx_analyze_upload_tables() RETURNS void
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
        BEGIN
            ANALYZE public.stored_file;
            ANALYZE public.gallery_image;
            ANALYZE public.photo_search_doc;
        END
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION public.hocx_analyze_upload_tables() FROM PUBLIC")
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hocx_app') THEN "
        "GRANT EXECUTE ON FUNCTION public.hocx_analyze_upload_tables() TO hocx_app; END IF; END $$"
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS public.hocx_analyze_upload_tables()")
    op.execute("DELETE FROM tenant_role_permission WHERE permission_key = 'files.import'")
    op.execute("DELETE FROM permission WHERE key = 'files.import'")
    op.execute("DROP TABLE IF EXISTS import_item")
    op.execute("DROP TABLE IF EXISTS import_job")
