"""Öffentliche Prüfung von PDFs: View mit der Freigabelogik und Funktion für die Abgabebox.

- View document_verification_public: liefert ausschliesslich die Felder der Prüfseite. Was
  angezeigt werden darf, entscheidet allein diese View:
    * Name, public_id und Logo-Hinweis des Mandanten nur mit tenant.verify_show_identity,
    * organization_verified nur mit Anzeige UND Bestätigung durch einen Plattform-Admin,
    * is_superseded / latest_version_label nur für Protokolle und nur mit
      tenant.verify_show_newer_version (sonst NULL).
- Funktion verify_document(sha256): SECURITY DEFINER, liefert höchstens eine Zeile für einen
  bekannten Hash. Die restricted Rolle hocx_abgabebox bekommt nur EXECUTE darauf - weder das
  Register noch die View selbst. Eine kompromittierte Abgabebox kann so keine Liste aller
  Dokumente auslesen, nur Hashes prüfen, die sie schon kennt.

PostgreSQL erlaubt PUBLIC standardmässig EXECUTE auf neue Funktionen - das wird hier entzogen.

Zusätzlich: hocx_abgabebox hatte seit dem 1.0.0-Baseline SELECT auf die ganze Tabelle tenant
(inkl. Abrechnungsnotizen und jetzt der Prüfseiten-Einstellungen). Die Abgabebox liest davon nur
id und storage_quota_bytes (abgabebox-backend/app/models.py); alles Weitere läuft über
SECURITY-DEFINER-Funktionen. Die Rolle bekommt deshalb nur noch diese zwei Spalten - sonst
könnte sie die Freigabe der View über die Basistabelle umgehen (z. B. alle Mandantennamen).

Revision ID: 0117_document_verify_public
Revises: 0116_document_registry
Create Date: 2026-10-14
"""

from alembic import op

revision = "0117_document_verify_public"
down_revision = "0116_document_registry"
branch_labels = None
depends_on = None

ABGABEBOX_ROLE = "hocx_abgabebox"

VIEW = """
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
    op.execute(VIEW)
    op.execute("REVOKE ALL ON public.document_verification_public FROM PUBLIC")
    op.execute(FUNCTION)
    op.execute("REVOKE ALL ON FUNCTION public.verify_document(text) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION public.verify_document(text) TO {ABGABEBOX_ROLE}")
    # Tabellen-Recht entziehen (nimmt die Spalten-Rechte mit), dann genau die benötigten Spalten
    op.execute(f"REVOKE SELECT ON TABLE public.tenant FROM {ABGABEBOX_ROLE}")
    op.execute(f"GRANT SELECT (id, storage_quota_bytes) ON TABLE public.tenant TO {ABGABEBOX_ROLE}")


def downgrade() -> None:
    op.execute(f"GRANT SELECT ON TABLE public.tenant TO {ABGABEBOX_ROLE}")
    op.execute("DROP FUNCTION IF EXISTS public.verify_document(text)")
    op.execute("DROP VIEW IF EXISTS public.document_verification_public")
