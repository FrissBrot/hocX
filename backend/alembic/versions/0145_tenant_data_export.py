"""Vereinsexport (Datenschutz-Audit PRIV-006/D2, Umsetzungsplan Paket 6)

Ein Mandanten-Admin bestellt einen Export aller Vereinsdaten für die Weiterarbeit (Excel, PDFs,
Fotos, Abgaben) als AES-ZIP. Weil das bei vielen Fotos dauert, baut ihn der Hintergrundjob
tenant_data_export; die Datei liegt danach 7 Tage im Objektspeicher und wird dann gelöscht.

Das ZIP-Passwort liegt nur bis zum Bau verschlüsselt (secret_crypto) in password_encrypted und
wird danach geleert. RLS wie die übrigen Mandantentabellen.

Revision ID: 0145_tenant_data_export
Revises: 0144_erasure_journal
Create Date: 2026-10-21
"""

from alembic import op

revision = "0145_tenant_data_export"
down_revision = "0144_erasure_journal"
branch_labels = None
depends_on = None

SCOPE = "(SELECT public.hocx_rls_tenant())"
BASE = f"({SCOPE} IS NULL OR tenant_id = {SCOPE})"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE tenant_data_export (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            tenant_id bigint NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            requested_by bigint REFERENCES app_user(id) ON DELETE SET NULL,
            status text NOT NULL DEFAULT 'queued',
            include_files boolean NOT NULL DEFAULT true,
            language text NOT NULL DEFAULT 'de',
            password_encrypted text,
            object_key text,
            filename text,
            size_bytes bigint,
            error text,
            created_at timestamptz NOT NULL DEFAULT now(),
            started_at timestamptz,
            finished_at timestamptz,
            expires_at timestamptz,
            CONSTRAINT ck_tenant_data_export_status CHECK (status IN ('queued', 'running', 'done', 'failed', 'expired'))
        )
        """
    )
    op.execute("CREATE INDEX idx_tenant_data_export_tenant ON tenant_data_export (tenant_id, created_at DESC)")
    op.execute("CREATE INDEX idx_tenant_data_export_status ON tenant_data_export (status)")
    op.execute(f"CREATE POLICY tenant_isolation ON public.tenant_data_export FOR ALL USING {BASE} WITH CHECK {BASE}")  # sql-ok: feste Policy-Ausdrücke
    op.execute("ALTER TABLE public.tenant_data_export ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS tenant_data_export")
