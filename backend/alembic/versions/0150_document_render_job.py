"""PDF-Export als Auftrag (Concurrency-Audit CONC-003/-004/-020, Nutzerentscheid: Job mit
Benachrichtigung).

POST /documents/render legte bisher im Request ein PDF an: Session bis ~80 s offen, Compile-Slots
der uvicorn-Worker geteilt mit Vorschau und Thumbnails aller Mandanten. Jetzt entsteht ein
Auftrag; der job-worker rendert ihn (reihum je Mandant, je Protokoll höchstens ein laufender
Auftrag), das Frontend fragt den Stand ab und meldet "PDF bereit". Auch das Auto-PDF nach dem
Abschliessen läuft so - dauerhaft, mit Wiederholung, statt als In-Prozess-BackgroundTask.

RLS wie die übrigen Mandantentabellen.

Revision ID: 0150_document_render_job
Revises: 0149_block_config_version
Create Date: 2026-10-21
"""

from alembic import op

revision = "0150_document_render_job"
down_revision = "0149_block_config_version"
branch_labels = None
depends_on = None

SCOPE = "(SELECT public.hocx_rls_tenant())"
BASE = f"({SCOPE} IS NULL OR tenant_id = {SCOPE})"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE document_render_job (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            tenant_id bigint NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            requested_by bigint REFERENCES app_user(id) ON DELETE SET NULL,
            protocol_id bigint REFERENCES protocol(id) ON DELETE CASCADE,
            request_json jsonb NOT NULL,
            status text NOT NULL DEFAULT 'queued',
            attempts integer NOT NULL DEFAULT 0,
            export_id bigint REFERENCES document_export(id) ON DELETE SET NULL,
            -- Kuratierte Fehlerantwort wie bisher die Route (render_error/http_error): Status + detail
            error_status integer,
            error jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            started_at timestamptz,
            finished_at timestamptz,
            CONSTRAINT ck_document_render_job_status CHECK (status IN ('queued', 'running', 'done', 'failed'))
        )
        """
    )
    op.execute("CREATE INDEX idx_document_render_job_queue ON document_render_job (status, created_at)")
    op.execute("CREATE INDEX idx_document_render_job_tenant ON document_render_job (tenant_id, created_at DESC)")
    op.execute("CREATE INDEX idx_document_render_job_protocol ON document_render_job (protocol_id) WHERE protocol_id IS NOT NULL")
    op.execute("CREATE INDEX idx_document_render_job_export ON document_render_job (export_id) WHERE export_id IS NOT NULL")
    op.execute(f"CREATE POLICY tenant_isolation ON public.document_render_job FOR ALL USING {BASE} WITH CHECK {BASE}")  # sql-ok: feste Policy-Ausdrücke
    op.execute("ALTER TABLE public.document_render_job ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS document_render_job")
