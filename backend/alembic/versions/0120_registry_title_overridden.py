"""Dokumentenregister: beim Export überschriebenen Protokolltitel vermerken

Audit STUDIO-007 (Entscheidung Nutzer 2026-10-16): Jede exportierende Person konnte den Titel
eines Protokoll-PDFs frei setzen; das PDF galt auf der Prüfseite als echt. Der Titel bleibt
änderbar, das Register vermerkt aber die Abweichung und die Prüfseite zeigt sie an (View und
Funktion aus 0117 erhalten die Spalte zusätzlich am Ende).

Revision ID: 0120_registry_title_overridden
Revises: 0119_studio_merge_main_fines
Create Date: 2026-10-16
"""
from alembic import op

revision = "0120_registry_title_overridden"
down_revision = "0119_studio_merge_main_fines"
branch_labels = None
depends_on = None

ABGABEBOX_ROLE = "hocx_abgabebox"

VIEW = """
CREATE OR REPLACE VIEW public.document_verification_public AS
SELECT
    r.sha256,
    r.public_id AS document_id,
    r.document_type,
    r.title,
    r.status_code,
    r.version_label,
    r.created_at,
    CASE WHEN t.verify_show_newer_version AND r.document_type = 'protocol' AND r.source_public_id IS NOT NULL
        THEN EXISTS (
            SELECT 1 FROM public.document_registry n
            WHERE n.tenant_id = r.tenant_id
              AND n.source_public_id = r.source_public_id
              AND (COALESCE(n.version_major, 0), COALESCE(n.version_minor, 0))
                > (COALESCE(r.version_major, 0), COALESCE(r.version_minor, 0))
        )
    END AS is_superseded,
    CASE WHEN t.verify_show_newer_version AND r.document_type = 'protocol' AND r.source_public_id IS NOT NULL
        THEN (
            SELECT n.version_label FROM public.document_registry n
            WHERE n.tenant_id = r.tenant_id
              AND n.source_public_id = r.source_public_id
              AND (COALESCE(n.version_major, 0), COALESCE(n.version_minor, 0))
                > (COALESCE(r.version_major, 0), COALESCE(r.version_minor, 0))
            ORDER BY COALESCE(n.version_major, 0) DESC, COALESCE(n.version_minor, 0) DESC, n.created_at DESC
            LIMIT 1
        )
    END AS latest_version_label,
    CASE WHEN t.verify_show_identity THEN t.name END AS tenant_name,
    CASE WHEN t.verify_show_identity THEN t.public_id END AS tenant_public_id,
    CASE WHEN t.verify_show_identity THEN t.profile_image_path IS NOT NULL END AS tenant_has_logo,
    (t.verify_show_identity AND t.identity_verified_at IS NOT NULL) AS organization_verified,
    r.title_overridden
FROM public.document_registry r
JOIN public.tenant t ON t.id = r.tenant_id
"""

FUNCTION = """
CREATE FUNCTION public.verify_document(p_sha256 text)
RETURNS TABLE (
    document_id uuid,
    document_type text,
    title text,
    status_code text,
    version_label text,
    created_at timestamptz,
    is_superseded boolean,
    latest_version_label text,
    tenant_name text,
    tenant_public_id uuid,
    tenant_has_logo boolean,
    organization_verified boolean,
    title_overridden boolean
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
    SELECT v.document_id, v.document_type, v.title, v.status_code, v.version_label, v.created_at,
           v.is_superseded, v.latest_version_label, v.tenant_name, v.tenant_public_id,
           v.tenant_has_logo, v.organization_verified, v.title_overridden
    FROM public.document_verification_public v
    WHERE p_sha256 ~ '^[0-9a-f]{64}$' AND v.sha256 = p_sha256
    LIMIT 1
$$
"""

VIEW_0117 = """
CREATE VIEW public.document_verification_public AS
SELECT
    r.sha256,
    r.public_id AS document_id,
    r.document_type,
    r.title,
    r.status_code,
    r.version_label,
    r.created_at,
    CASE WHEN t.verify_show_newer_version AND r.document_type = 'protocol' AND r.source_public_id IS NOT NULL
        THEN EXISTS (
            SELECT 1 FROM public.document_registry n
            WHERE n.tenant_id = r.tenant_id
              AND n.source_public_id = r.source_public_id
              AND (COALESCE(n.version_major, 0), COALESCE(n.version_minor, 0))
                > (COALESCE(r.version_major, 0), COALESCE(r.version_minor, 0))
        )
    END AS is_superseded,
    CASE WHEN t.verify_show_newer_version AND r.document_type = 'protocol' AND r.source_public_id IS NOT NULL
        THEN (
            SELECT n.version_label FROM public.document_registry n
            WHERE n.tenant_id = r.tenant_id
              AND n.source_public_id = r.source_public_id
              AND (COALESCE(n.version_major, 0), COALESCE(n.version_minor, 0))
                > (COALESCE(r.version_major, 0), COALESCE(r.version_minor, 0))
            ORDER BY COALESCE(n.version_major, 0) DESC, COALESCE(n.version_minor, 0) DESC, n.created_at DESC
            LIMIT 1
        )
    END AS latest_version_label,
    CASE WHEN t.verify_show_identity THEN t.name END AS tenant_name,
    CASE WHEN t.verify_show_identity THEN t.public_id END AS tenant_public_id,
    CASE WHEN t.verify_show_identity THEN t.profile_image_path IS NOT NULL END AS tenant_has_logo,
    (t.verify_show_identity AND t.identity_verified_at IS NOT NULL) AS organization_verified
FROM public.document_registry r
JOIN public.tenant t ON t.id = r.tenant_id
"""

FUNCTION_0117 = """
CREATE FUNCTION public.verify_document(p_sha256 text)
RETURNS TABLE (
    document_id uuid,
    document_type text,
    title text,
    status_code text,
    version_label text,
    created_at timestamptz,
    is_superseded boolean,
    latest_version_label text,
    tenant_name text,
    tenant_public_id uuid,
    tenant_has_logo boolean,
    organization_verified boolean
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
    SELECT v.document_id, v.document_type, v.title, v.status_code, v.version_label, v.created_at,
           v.is_superseded, v.latest_version_label, v.tenant_name, v.tenant_public_id,
           v.tenant_has_logo, v.organization_verified
    FROM public.document_verification_public v
    WHERE p_sha256 ~ '^[0-9a-f]{64}$' AND v.sha256 = p_sha256
    LIMIT 1
$$
"""


def upgrade() -> None:
    op.execute("ALTER TABLE document_registry ADD COLUMN title_overridden boolean NOT NULL DEFAULT false")
    # Rückgabetyp ändert sich: Funktion neu anlegen, View um die Spalte am Ende erweitern.
    op.execute("DROP FUNCTION public.verify_document(text)")
    op.execute(VIEW)
    op.execute(FUNCTION)
    op.execute("REVOKE ALL ON FUNCTION public.verify_document(text) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION public.verify_document(text) TO {ABGABEBOX_ROLE}")


def downgrade() -> None:
    op.execute("DROP FUNCTION public.verify_document(text)")
    op.execute("DROP VIEW public.document_verification_public")
    op.execute(VIEW_0117)
    op.execute("REVOKE ALL ON public.document_verification_public FROM PUBLIC")
    op.execute(FUNCTION_0117)
    op.execute("REVOKE ALL ON FUNCTION public.verify_document(text) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION public.verify_document(text) TO {ABGABEBOX_ROLE}")
    op.execute("ALTER TABLE document_registry DROP COLUMN title_overridden")
