"""Prüfseite: Zuordnung über die Dokument-ID und Seitenvergleich

- document_registry.page_fingerprints: je Seite ein Fingerabdruck des Seitentexts (16 Hex-Zeichen
  eines SHA-256 über den normalisierten Text, mit der Dokument-ID gesalzen;
  app/documents/page_fingerprints.py). Kein Text, kein PDF - nur für PDFs ab diesem Update.
- Funktion verify_document_pages(document_id, fingerprints): SECURITY DEFINER wie
  verify_document. Für eine veränderte Datei (Hash unbekannt), deren Dokument-ID die Prüfseite im
  Browser ausgelesen hat: Angaben wie verify_document nur bei freigegebener Anzeige der
  Organisation, sonst nur Zuordnung; dazu die Seitenzahl und je Seite nur «stimmt / stimmt
  nicht» (höchstens 150 Seiten). Gespeicherte
  Fingerabdrücke und der Hash verlassen die Datenbank nie. Die Rolle hocx_abgabebox bekommt nur
  EXECUTE.

Revision ID: 0185_document_page_fingerprints
Revises: 0184_event_times_program
Create Date: 2026-11-18
"""
from alembic import op

revision = "0185_document_page_fingerprints"
down_revision = "0184_event_times_program"
branch_labels = None
depends_on = None

ABGABEBOX_ROLE = "hocx_abgabebox"

FUNCTION = """
CREATE FUNCTION public.verify_document_pages(p_document_id uuid, p_fingerprints text[])
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
    import_unverified boolean,
    title_overridden boolean,
    verify_domain text,
    page_count integer,
    page_matches boolean[]
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
    -- Ohne Hash-Treffer reicht die Dokument-ID allein: Angaben über das Dokument (Titel, Status,
    -- Version, Datum) nur, wenn die Organisation ihre Anzeige freigegeben hat. Sonst nur die
    -- Zuordnung und der Seitenvergleich (Sicherheitsreview 2026-11-18).
    SELECT v.document_id, v.document_type,
           CASE WHEN v.tenant_name IS NOT NULL THEN v.title END,
           CASE WHEN v.tenant_name IS NOT NULL THEN v.status_code END,
           CASE WHEN v.tenant_name IS NOT NULL THEN v.version_label END,
           CASE WHEN v.tenant_name IS NOT NULL THEN v.created_at END,
           CASE WHEN v.tenant_name IS NOT NULL THEN v.is_superseded END,
           CASE WHEN v.tenant_name IS NOT NULL THEN v.latest_version_label END,
           v.tenant_name, v.tenant_public_id, v.tenant_has_logo, v.organization_verified,
           CASE WHEN v.tenant_name IS NOT NULL THEN v.import_unverified END,
           CASE WHEN v.tenant_name IS NOT NULL THEN v.title_overridden END,
           v.verify_domain,
           cardinality(r.page_fingerprints),
           CASE WHEN r.page_fingerprints IS NOT NULL THEN ARRAY(
               SELECT COALESCE(r.page_fingerprints[i] = p_fingerprints[i], false)
               FROM generate_subscripts(r.page_fingerprints, 1) AS i
               ORDER BY i
           ) END
    FROM public.document_registry r
    JOIN public.document_verification_public v ON v.document_id = r.public_id
    WHERE r.public_id = p_document_id
      AND cardinality(COALESCE(p_fingerprints, ARRAY[]::text[])) <= 150
    LIMIT 1
$$
"""


def upgrade() -> None:
    op.execute("ALTER TABLE document_registry ADD COLUMN page_fingerprints text[]")
    op.execute(FUNCTION)
    op.execute("REVOKE ALL ON FUNCTION public.verify_document_pages(uuid, text[]) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION public.verify_document_pages(uuid, text[]) TO {ABGABEBOX_ROLE}")


def downgrade() -> None:
    op.execute("DROP FUNCTION public.verify_document_pages(uuid, text[])")
    op.execute("ALTER TABLE document_registry DROP COLUMN page_fingerprints")
