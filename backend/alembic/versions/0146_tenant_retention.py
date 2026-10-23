"""Aufbewahrungsfristen je Verein (Datenschutz-Audit G, Umsetzungsplan Paket 8)

- tenant_retention_policy: Fristen des Vereins, alle standardmässig aus (NULL). Einreichungen X
  Monate nach Abgabeschluss löschen, ehemalige Mitglieder X Jahre nach Austritt deaktivieren
  (nichts löschen), Galeriebilder ohne Album und Termin nach X Jahren nur vorschlagen.
- retention_proposal: Vorschläge des Jobs retention_proposals, vom Mandanten-Admin bestätigt
  oder verworfen (verworfene werden nicht erneut vorgeschlagen).
- tenant.contract_ends_on: Vertragsende für das Offboarding (Check tenant_offboarding).

Beide Tabellen mit RLS wie die übrigen Mandantentabellen.

Revision ID: 0146_tenant_retention
Revises: 0145_tenant_data_export
Create Date: 2026-10-21
"""

from alembic import op

revision = "0146_tenant_retention"
down_revision = "0145_tenant_data_export"
branch_labels = None
depends_on = None

SCOPE = "(SELECT public.hocx_rls_tenant())"
BASE = f"({SCOPE} IS NULL OR tenant_id = {SCOPE})"
TABLES = ("tenant_retention_policy", "retention_proposal")


def upgrade() -> None:
    op.execute("ALTER TABLE tenant ADD COLUMN contract_ends_on date")
    op.execute(
        """
        CREATE TABLE tenant_retention_policy (
            tenant_id bigint PRIMARY KEY REFERENCES tenant(id) ON DELETE CASCADE,
            submissions_months smallint CHECK (submissions_months > 0),
            former_members_years smallint CHECK (former_members_years > 0),
            unlinked_gallery_years smallint CHECK (unlinked_gallery_years > 0),
            auto_apply boolean NOT NULL DEFAULT false,
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE retention_proposal (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            tenant_id bigint NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            kind text NOT NULL,
            subject_id bigint NOT NULL,
            label text,
            reference_date date,
            status text NOT NULL DEFAULT 'open',
            created_at timestamptz NOT NULL DEFAULT now(),
            decided_at timestamptz,
            decided_by bigint REFERENCES app_user(id) ON DELETE SET NULL,
            CONSTRAINT ck_retention_proposal_kind CHECK (kind IN ('submission_upload', 'former_member', 'gallery_image')),
            CONSTRAINT ck_retention_proposal_status CHECK (status IN ('open', 'applied', 'dismissed')),
            CONSTRAINT uq_retention_proposal_subject UNIQUE (tenant_id, kind, subject_id)
        )
        """
    )
    op.execute("CREATE INDEX idx_retention_proposal_open ON retention_proposal (tenant_id, status)")
    for table in TABLES:
        op.execute(f"CREATE POLICY tenant_isolation ON public.{table} FOR ALL USING {BASE} WITH CHECK {BASE}")  # sql-ok: feste Tabellen/Policy
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")  # sql-ok: feste Tabellen


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS retention_proposal")
    op.execute("DROP TABLE IF EXISTS tenant_retention_policy")
    op.execute("ALTER TABLE tenant DROP COLUMN IF EXISTS contract_ends_on")
