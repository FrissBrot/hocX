"""Audit-Log als Sicherheitsnachweis (Datenschutz-Audit PRIV-013, Umsetzungsplan Paket 3)

- ``ip_hash``: gekürzte (IPv4 /24, IPv6 /48), mit einem Server-Schlüssel gehashte Quelladresse.
  Damit lassen sich Zugriffe einer Quelle zusammenfassen, ohne die Adresse zu speichern.
- ``outcome``: ``success`` oder ``failure`` (z. B. fehlgeschlagene Anmeldung).
- Die Laufzeitrolle ``hocx_app`` darf Einträge nur noch anlegen und lesen. Löschen nach Frist und
  das Entfernen von E-Mail-Adressen gelöschter Personen laufen über SECURITY-DEFINER-Funktionen,
  die genau das und nichts anderes können.

Revision ID: 0143_audit_log_security
Revises: 0142_photo_worker_upload_rls
Create Date: 2026-10-21
"""

from alembic import op

revision = "0143_audit_log_security"
down_revision = "0142_photo_worker_upload_rls"
branch_labels = None
depends_on = None

FUNCTIONS = (
    """
    CREATE OR REPLACE FUNCTION public.audit_log_purge(p_retention_days integer)
    RETURNS bigint
    LANGUAGE plpgsql
    SECURITY DEFINER
    SET search_path = pg_catalog, public
    AS $$
    DECLARE
        deleted bigint;
    BEGIN
        IF p_retention_days IS NULL OR p_retention_days < 30 THEN
            RAISE EXCEPTION 'audit_log_purge: Frist muss mindestens 30 Tage betragen';
        END IF;
        DELETE FROM public.audit_log WHERE created_at < now() - make_interval(days => p_retention_days);
        GET DIAGNOSTICS deleted = ROW_COUNT;
        RETURN deleted;
    END
    $$
    """,
    # Vor dem Löschen von Personen bzw. Mandanten: E-Mail und IP-Hash entfernen, die Aktion bleibt.
    """
    CREATE OR REPLACE FUNCTION public.audit_log_forget_actors(p_user_ids bigint[])
    RETURNS bigint
    LANGUAGE plpgsql
    SECURITY DEFINER
    SET search_path = pg_catalog, public
    AS $$
    DECLARE
        changed bigint;
    BEGIN
        UPDATE public.audit_log SET actor_email = NULL, ip_hash = NULL
        WHERE actor_user_id = ANY(p_user_ids) AND (actor_email IS NOT NULL OR ip_hash IS NOT NULL);
        GET DIAGNOSTICS changed = ROW_COUNT;
        RETURN changed;
    END
    $$
    """,
    """
    CREATE OR REPLACE FUNCTION public.audit_log_forget_tenant(p_tenant_id bigint)
    RETURNS bigint
    LANGUAGE plpgsql
    SECURITY DEFINER
    SET search_path = pg_catalog, public
    AS $$
    DECLARE
        changed bigint;
    BEGIN
        UPDATE public.audit_log SET actor_email = NULL, ip_hash = NULL
        WHERE tenant_id = p_tenant_id AND actor_user_id IS NOT NULL;
        GET DIAGNOSTICS changed = ROW_COUNT;
        RETURN changed;
    END
    $$
    """,
)


def upgrade() -> None:
    op.execute("ALTER TABLE audit_log ADD COLUMN ip_hash text")
    op.execute("ALTER TABLE audit_log ADD COLUMN outcome text NOT NULL DEFAULT 'success'")
    op.execute("ALTER TABLE audit_log ADD CONSTRAINT ck_audit_log_outcome CHECK (outcome IN ('success', 'failure'))")
    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_tenant_created ON audit_log (tenant_id, created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_action_created ON audit_log (action, created_at DESC)")
    for statement in FUNCTIONS:
        op.execute(statement)
    for name, args in (("audit_log_purge", "integer"), ("audit_log_forget_actors", "bigint[]"), ("audit_log_forget_tenant", "bigint")):
        op.execute(f"REVOKE ALL ON FUNCTION public.{name}({args}) FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION public.{name}({args}) TO hocx_app")
    op.execute("REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM hocx_app")


def downgrade() -> None:
    op.execute("GRANT UPDATE, DELETE ON audit_log TO hocx_app")
    op.execute("DROP FUNCTION IF EXISTS public.audit_log_forget_tenant(bigint)")
    op.execute("DROP FUNCTION IF EXISTS public.audit_log_forget_actors(bigint[])")
    op.execute("DROP FUNCTION IF EXISTS public.audit_log_purge(integer)")
    op.execute("DROP INDEX IF EXISTS idx_audit_log_action_created")
    op.execute("DROP INDEX IF EXISTS idx_audit_log_tenant_created")
    op.execute("ALTER TABLE audit_log DROP CONSTRAINT IF EXISTS ck_audit_log_outcome")
    op.execute("ALTER TABLE audit_log DROP COLUMN IF EXISTS outcome")
    op.execute("ALTER TABLE audit_log DROP COLUMN IF EXISTS ip_hash")
