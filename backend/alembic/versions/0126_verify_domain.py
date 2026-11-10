"""Eigene Prüf-Domain je Mandant (z. B. verify.verein.ch)

- Neues Feature 'verify_domain', unabhängig von 'custom_domain' buchbar (keinem Plan
  vorbelegt - der Plattform-Admin ordnet es Plänen oder einzelnen Mandanten zu).
- tenant_domain bekommt den Zweck 'verify' (eine Prüf-Domain je Mandant, wie bei app/abgabebox).
- View document_verification_public/Funktion verify_document liefern zusätzlich verify_domain:
  die aktive, gesunde Prüf-Domain des ausstellenden Mandanten, nur bei gebuchtem Feature und
  freigegebener Anzeige von Name und Logo (sonst NULL). Die Prüfseite leitet damit auf die
  Seite des Mandanten weiter.
- Funktion verify_site(domain): SECURITY DEFINER wie verify_document. Liefert für eine aktive
  Prüf-Domain Name, Logo-Hinweis und Bestätigungsstatus des Mandanten (Kopf der Prüfseite unter
  der Mandanten-Domain). Die Rolle hocx_abgabebox bekommt nur EXECUTE, keinen Tabellenzugriff
  auf tenant_domain.

Revision ID: 0126_verify_domain
Revises: 0125_release_merge_imgmeta
Create Date: 2026-10-17
"""
from alembic import op

revision = "0126_verify_domain"
down_revision = "0125_release_merge_imgmeta"
branch_labels = None
depends_on = None

ABGABEBOX_ROLE = "hocx_abgabebox"

# Spaltenteil der View bis title_overridden, unverändert aus 0120
_VIEW_COLUMNS = """
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
    r.import_unverified,
    r.title_overridden"""

VIEW = f"""
CREATE OR REPLACE VIEW public.document_verification_public AS
SELECT{_VIEW_COLUMNS},
    CASE WHEN t.verify_show_identity THEN (
        SELECT d.domain FROM public.tenant_domain d
        WHERE d.tenant_id = t.id
          AND d.purpose = 'verify'
          AND d.status = 'active'
          AND d.is_healthy
          AND EXISTS (
              SELECT 1 FROM public.tenant_feature f
              WHERE f.tenant_id = t.id AND f.feature_code = 'verify_domain'
          )
        LIMIT 1
    ) END AS verify_domain
FROM public.document_registry r
JOIN public.tenant t ON t.id = r.tenant_id
"""

VIEW_0120 = f"""
CREATE VIEW public.document_verification_public AS
SELECT{_VIEW_COLUMNS}
FROM public.document_registry r
JOIN public.tenant t ON t.id = r.tenant_id
"""

_FUNCTION_TEMPLATE = """
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
    import_unverified boolean,
    title_overridden boolean{extra_type}
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
    SELECT v.document_id, v.document_type, v.title, v.status_code, v.version_label, v.created_at,
           v.is_superseded, v.latest_version_label, v.tenant_name, v.tenant_public_id,
           v.tenant_has_logo, v.organization_verified, v.import_unverified, v.title_overridden{extra_column}
    FROM public.document_verification_public v
    WHERE p_sha256 ~ '^[0-9a-f]{{64}}$' AND v.sha256 = p_sha256
    LIMIT 1
$$
"""

FUNCTION = _FUNCTION_TEMPLATE.format(extra_type=",\n    verify_domain text", extra_column=", v.verify_domain")
FUNCTION_0120 = _FUNCTION_TEMPLATE.format(extra_type="", extra_column="")

SITE_FUNCTION = """
CREATE FUNCTION public.verify_site(p_domain text)
RETURNS TABLE (
    domain text,
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
    SELECT d.domain, t.name, t.public_id, t.profile_image_path IS NOT NULL, t.identity_verified_at IS NOT NULL
    FROM public.tenant_domain d
    JOIN public.tenant t ON t.id = d.tenant_id
    WHERE d.domain = lower(p_domain)
      AND d.purpose = 'verify'
      AND d.status = 'active'
      AND t.verify_show_identity
      AND EXISTS (
          SELECT 1 FROM public.tenant_feature f
          WHERE f.tenant_id = t.id AND f.feature_code = 'verify_domain'
      )
    LIMIT 1
$$
"""


def _grant_functions() -> None:
    op.execute("REVOKE ALL ON FUNCTION public.verify_document(text) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION public.verify_document(text) TO {ABGABEBOX_ROLE}")


def upgrade() -> None:
    op.execute(
        "INSERT INTO feature (code, name, description) VALUES "
        "('verify_domain', 'Eigene Prüf-Domain', "
        "'Eigene Domain für die öffentliche Echtheitsprüfung (z. B. verify.verein.ch)') "
        "ON CONFLICT (code) DO NOTHING"
    )
    op.execute("ALTER TABLE tenant_domain DROP CONSTRAINT ck_tenant_domain_purpose")
    op.execute(
        "ALTER TABLE tenant_domain ADD CONSTRAINT ck_tenant_domain_purpose "
        "CHECK (purpose IN ('app', 'abgabebox', 'verify'))"
    )
    # Rückgabetyp ändert sich: Funktion neu anlegen, View um die Spalte am Ende erweitern.
    op.execute("DROP FUNCTION public.verify_document(text)")
    op.execute(VIEW)
    op.execute(FUNCTION)
    _grant_functions()
    op.execute(SITE_FUNCTION)
    op.execute("REVOKE ALL ON FUNCTION public.verify_site(text) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION public.verify_site(text) TO {ABGABEBOX_ROLE}")


def downgrade() -> None:
    op.execute("DROP FUNCTION public.verify_site(text)")
    op.execute("DROP FUNCTION public.verify_document(text)")
    op.execute("DROP VIEW public.document_verification_public")
    op.execute(VIEW_0120)
    op.execute("REVOKE ALL ON public.document_verification_public FROM PUBLIC")
    op.execute(FUNCTION_0120)
    _grant_functions()
    op.execute("DELETE FROM tenant_domain WHERE purpose = 'verify'")
    op.execute("ALTER TABLE tenant_domain DROP CONSTRAINT ck_tenant_domain_purpose")
    op.execute(
        "ALTER TABLE tenant_domain ADD CONSTRAINT ck_tenant_domain_purpose CHECK (purpose IN ('app', 'abgabebox'))"
    )
    op.execute("DELETE FROM feature WHERE code = 'verify_domain'")
