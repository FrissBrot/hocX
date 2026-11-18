"""Abgabebox: Speicher-Funktionen und Kontingent nur für den Mandanten des gesetzten Links

0133_abgabebox_rls bindet die Rolle hocx_abgabebox an das Link-Token, damit ein übernommener
öffentlicher Dienst ohne gültiges Token keinen anderen Mandanten erreicht. Daran vorbei gingen:

- upload_storage_usage(p_tenant_id): Speicherbelegung jedes beliebigen Mandanten,
- storage_usage_bytes(p_namespace, p_prefix): Objektregister jedes Namespace und Präfixes,
- storage_backup_hold(p_namespace, ...): Prüfsumme/Grösse beliebiger Objekte (auch "main"),
- das Spaltenrecht auf tenant (id, storage_quota_bytes, 0090): alle Mandanten samt Kontingent.

Für session_user = hocx_abgabebox (wie storage_active_config, 0115) gilt jetzt: Belegung und
Präfixe nur für den Mandanten des Links, Objektregister nur im Namespace "abgabebox"; das
Kontingent liefert abgabebox_storage_quota() für den Link-Mandanten (Muster 0147), das
Spaltenrecht auf tenant entfällt. Für hocx_app und die Migrationsrolle ändert sich nichts.

Revision ID: 0183_abgabebox_link_scope
Revises: 0182_submission_completion
Create Date: 2026-11-18
"""

from alembic import op

revision = "0183_abgabebox_link_scope"
down_revision = "0182_submission_completion"
branch_labels = None
depends_on = None

ROLE = "hocx_abgabebox"
_DENIED = "RAISE EXCEPTION '% not permitted for %', {what}, session_user USING ERRCODE = '42501';"

UPLOAD_USAGE = f"""
CREATE OR REPLACE FUNCTION public.upload_storage_usage(p_tenant_id bigint) RETURNS bigint
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
BEGIN
  IF session_user = '{ROLE}' AND p_tenant_id IS DISTINCT FROM public.hocx_rls_abgabebox_tenant() THEN
    {_DENIED.format(what="'storage usage of tenant ' || p_tenant_id")}
  END IF;
  RETURN COALESCE((SELECT SUM(file_size_bytes) FROM public.stored_file WHERE tenant_id = p_tenant_id), 0)::bigint
       + COALESCE((SELECT SUM(reserved_bytes) FROM public.gallery_upload_job
           WHERE tenant_id = p_tenant_id AND status IN ('queued', 'running')), 0)::bigint;
END
$$
"""

STORAGE_USAGE = f"""
CREATE OR REPLACE FUNCTION public.storage_usage_bytes(p_namespace text, p_prefix text) RETURNS bigint
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE
  v_tenant bigint;
BEGIN
  IF session_user = '{ROLE}' THEN
    v_tenant := public.hocx_rls_abgabebox_tenant();
    IF p_namespace IS DISTINCT FROM 'abgabebox' OR v_tenant IS NULL OR p_prefix IS NULL
       OR NOT (left(p_prefix, length('tenant-' || v_tenant || '/')) = 'tenant-' || v_tenant || '/'
               OR left(p_prefix, length('quarantine/tenant-' || v_tenant || '/')) = 'quarantine/tenant-' || v_tenant || '/') THEN
      {_DENIED.format(what="'storage usage of ' || p_namespace || ':' || COALESCE(p_prefix, '')")}
    END IF;
  END IF;
  RETURN (SELECT COALESCE(SUM(o.size_bytes), 0)::bigint FROM public.storage_object o
          WHERE o.namespace = p_namespace AND o.status = 'active'
            AND left(o.key, length(p_prefix)) = p_prefix);
END
$$
"""

BACKUP_HOLD = f"""
CREATE OR REPLACE FUNCTION public.storage_backup_hold(p_namespace text, p_key text, p_generation bigint)
RETURNS TABLE(hold_id uuid, sha256 text, size_bytes bigint)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
BEGIN
  -- Ohne Mandantenbindung: das Quarantäne-Aufräumen der Abgabebox läuft ohne Link.
  IF session_user = '{ROLE}' AND p_namespace IS DISTINCT FROM 'abgabebox' THEN
    {_DENIED.format(what="'backup hold in ' || COALESCE(p_namespace, '')")}
  END IF;
  RETURN QUERY
    SELECT s.backup_hold_id, o.sha256, o.size_bytes
    FROM public.storage_state s
    JOIN public.storage_object o ON o.namespace = p_namespace AND o.key = p_key
    WHERE s.id = 1 AND s.backup_hold_id IS NOT NULL AND s.backup_hold_generation = p_generation
      AND (o.status = 'active' OR (o.status = 'deleted' AND o.purge_pending)) AND o.sha256 IS NOT NULL;
END
$$
"""

QUOTA = """
CREATE FUNCTION public.abgabebox_storage_quota() RETURNS bigint
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    SELECT t.storage_quota_bytes FROM public.tenant t WHERE t.id = public.hocx_rls_abgabebox_tenant()
$$
"""

# Vorherige Fassungen (0092_upload_capacity, 0115_backup_system/0123_backup_hold_tombstones).
UPLOAD_USAGE_OLD = """
CREATE OR REPLACE FUNCTION public.upload_storage_usage(p_tenant_id bigint) RETURNS bigint
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
  SELECT COALESCE((SELECT SUM(file_size_bytes) FROM public.stored_file WHERE tenant_id=p_tenant_id),0)::bigint
       + COALESCE((SELECT SUM(reserved_bytes) FROM public.gallery_upload_job
           WHERE tenant_id=p_tenant_id AND status IN ('queued','running')),0)::bigint
$$
"""

STORAGE_USAGE_OLD = """
CREATE OR REPLACE FUNCTION public.storage_usage_bytes(p_namespace text, p_prefix text) RETURNS bigint
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
  SELECT COALESCE(SUM(o.size_bytes), 0)::bigint FROM public.storage_object o
  WHERE o.namespace = p_namespace AND o.status = 'active'
    AND left(o.key, length(p_prefix)) = p_prefix
$$
"""

BACKUP_HOLD_OLD = """
CREATE OR REPLACE FUNCTION public.storage_backup_hold(p_namespace text, p_key text, p_generation bigint)
RETURNS TABLE(hold_id uuid, sha256 text, size_bytes bigint)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
  SELECT s.backup_hold_id, o.sha256, o.size_bytes
  FROM public.storage_state s
  JOIN public.storage_object o ON o.namespace = p_namespace AND o.key = p_key
  WHERE s.id = 1 AND s.backup_hold_id IS NOT NULL AND s.backup_hold_generation = p_generation
    AND (o.status = 'active' OR (o.status = 'deleted' AND o.purge_pending)) AND o.sha256 IS NOT NULL
$$
"""


def upgrade() -> None:
    # CREATE OR REPLACE behält Eigentümer und EXECUTE-Rechte.
    op.execute(UPLOAD_USAGE)
    op.execute(STORAGE_USAGE)
    op.execute(BACKUP_HOLD)
    op.execute(QUOTA)
    op.execute("REVOKE ALL ON FUNCTION public.abgabebox_storage_quota() FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION public.abgabebox_storage_quota() TO {ROLE}")
    op.execute(f"REVOKE SELECT (id, storage_quota_bytes) ON TABLE tenant FROM {ROLE}")


def downgrade() -> None:
    op.execute(f"GRANT SELECT (id, storage_quota_bytes) ON TABLE tenant TO {ROLE}")
    op.execute("DROP FUNCTION IF EXISTS public.abgabebox_storage_quota()")
    op.execute(BACKUP_HOLD_OLD)
    op.execute(STORAGE_USAGE_OLD)
    op.execute(UPLOAD_USAGE_OLD)
