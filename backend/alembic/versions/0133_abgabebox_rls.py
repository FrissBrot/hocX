"""Row-Level-Security für die öffentliche Abgabebox, gebunden an das Link-Token

Security-Audit release/1.2.0, SEC-008: Die Rolle hocx_abgabebox gehört zum öffentlich erreichbaren
Dienst und konnte Dateinamen, GPS-Daten, Speicherpfade, Termine, Listen und Namen ALLER Mandanten
lesen; die Trennung lag nur im Code (Link-Token -> Mandant).

Ein Mandanten-Kontext wie bei hocx_app (0132_tenant_rls) hilft hier wenig: wer den Dienst
übernimmt, kann `app.tenant_id` selbst setzen. Die Abgabebox setzt deshalb das geheime Link-Token
(`app.abgabebox_link`, abgabebox-backend/app/repository.py::get_link_by_token), und die Datenbank
leitet den Mandanten daraus ab (`hocx_rls_abgabebox_tenant`). Fremde Daten erreicht nur, wer ein
gültiges Token des anderen Mandanten kennt.

- Policies aus 0132 gelten nur noch für hocx_app und hocx_photo_worker; hocx_abgabebox bekommt
  eigene, strikte Policies (ohne Token: keine Zeilen).
- Tabellen ohne tenant_id, die die Abgabebox liest oder schreibt (Listeneinträge, Upload-Tabellen,
  Verknüpfungen), werden über ihre Elterntabelle geprüft; für die anderen Rollen bleiben sie offen.
- Spaltenrechte auf stored_file auf das Nötige reduziert (kein GPS, keine Namen, keine Pfade).

Revision ID: 0133_abgabebox_rls
Revises: 0132_tenant_rls
Create Date: 2026-10-20
"""

from alembic import op

revision = "0133_abgabebox_rls"
down_revision = "0132_tenant_rls"
branch_labels = None
depends_on = None

ROLE = "hocx_abgabebox"
OTHER_ROLES = "hocx_app, hocx_photo_worker"
POLICY = "tenant_isolation_abgabebox"
OPEN_POLICY = "tenant_isolation_open"

LINK_TENANT = "(SELECT public.hocx_rls_abgabebox_tenant())"

# Tabellen mit tenant_id, auf die hocx_abgabebox Rechte hat.
TENANT_TABLES = (
    "app_user",
    "cycle_config",
    "event",
    "list_definition",
    "stored_file",
    "submission_assignment",
    "tenant_feature",
)

# Tabellen ohne tenant_id: Bedingung über die (selbst RLS-geschützte) Elterntabelle.
CHILD_TABLES = {
    "event_cycle": "EXISTS (SELECT 1 FROM public.event p WHERE p.id = event_cycle.event_id)",
    "list_entry": "EXISTS (SELECT 1 FROM public.list_definition p WHERE p.id = list_entry.list_definition_id)",
    "submission_assignment_link": (
        "EXISTS (SELECT 1 FROM public.submission_assignment p WHERE p.id = submission_assignment_link.assignment_id)"
    ),
    "submission_upload": (
        "EXISTS (SELECT 1 FROM public.submission_assignment p WHERE p.id = submission_upload.assignment_id)"
    ),
    "submission_upload_file": (
        "EXISTS (SELECT 1 FROM public.submission_upload p WHERE p.id = submission_upload_file.upload_id)"
    ),
    "submission_upload_log": (
        "EXISTS (SELECT 1 FROM public.submission_assignment p WHERE p.id = submission_upload_log.assignment_id)"
    ),
}

# Was die Abgabebox von stored_file wirklich liest (Duplikat-/Ähnlichkeitsprüfung, INSERT ... RETURNING id).
STORED_FILE_SELECT_COLUMNS = ("id", "tenant_id", "checksum_sha256", "perceptual_hash")


def _rls_policies(conn) -> list[tuple[str, str]]:
    rows = conn.exec_driver_sql(
        "SELECT tablename, policyname FROM pg_policies "
        "WHERE schemaname = 'public' AND policyname IN ('tenant_isolation', 'tenant_isolation_read')"
    )
    return [(row[0], row[1]) for row in rows]


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.hocx_rls_abgabebox_tenant() RETURNS bigint
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
        AS $$
            SELECT tenant_id FROM submission_link
             WHERE token = NULLIF(current_setting('app.abgabebox_link', true), '')
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION public.hocx_rls_abgabebox_tenant() FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION public.hocx_rls_abgabebox_tenant() TO {ROLE}")

    conn = op.get_bind()
    for table, policy in _rls_policies(conn):
        op.execute(f"ALTER POLICY {policy} ON public.{table} TO {OTHER_ROLES}")

    for table in TENANT_TABLES:
        op.execute(
            f"CREATE POLICY {POLICY} ON public.{table} FOR ALL TO {ROLE} "
            f"USING (tenant_id = {LINK_TENANT}) WITH CHECK (tenant_id = {LINK_TENANT})"
        )
    # Der eigene Link, nicht die anderen Links (und deren Tokens) desselben Mandanten.
    op.execute(
        f"CREATE POLICY {POLICY} ON public.submission_link FOR SELECT TO {ROLE} "
        "USING (token = NULLIF(current_setting('app.abgabebox_link', true), ''))"
    )

    for table, condition in CHILD_TABLES.items():
        op.execute(f"CREATE POLICY {OPEN_POLICY} ON public.{table} FOR ALL TO {OTHER_ROLES} USING (true) WITH CHECK (true)")
        op.execute(f"CREATE POLICY {POLICY} ON public.{table} FOR ALL TO {ROLE} USING ({condition}) WITH CHECK ({condition})")
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")

    op.execute(f"REVOKE SELECT ON public.stored_file FROM {ROLE}")
    op.execute(f"GRANT SELECT ({', '.join(STORED_FILE_SELECT_COLUMNS)}) ON public.stored_file TO {ROLE}")


def downgrade() -> None:
    conn = op.get_bind()
    columns = [
        row[0]
        for row in conn.exec_driver_sql(
            "SELECT column_name FROM information_schema.column_privileges "
            f"WHERE grantee = '{ROLE}' AND table_name = 'stored_file' AND privilege_type = 'INSERT'"
        )
    ]
    if columns:
        op.execute(f"GRANT SELECT ({', '.join(columns)}) ON public.stored_file TO {ROLE}")

    for table in CHILD_TABLES:
        op.execute(f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS {POLICY} ON public.{table}")
        op.execute(f"DROP POLICY IF EXISTS {OPEN_POLICY} ON public.{table}")
    op.execute(f"DROP POLICY IF EXISTS {POLICY} ON public.submission_link")
    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {POLICY} ON public.{table}")
    for table, policy in _rls_policies(conn):
        op.execute(f"ALTER POLICY {policy} ON public.{table} TO PUBLIC")
    op.execute("DROP FUNCTION IF EXISTS public.hocx_rls_abgabebox_tenant()")
