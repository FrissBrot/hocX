"""Row-Level-Security für Mandantendaten (zweites Sicherheitsnetz)

Security-Audit release/1.2.0 (SEC-008): Die Mandantentrennung lag bisher nur im Anwendungscode
(jede Abfrage filtert selbst nach tenant_id). Ein vergessener Filter wurde so direkt zu einem
Cross-Tenant-Leck (vgl. SEC-003). Jetzt prüft zusätzlich PostgreSQL jede Zeile:

- Das Backend setzt bei jeder Transaktion einer angemeldeten Mandanten-Anfrage
  `app.tenant_id` (app/core/tenant_scope.py). Dann sind nur Zeilen dieses Mandanten sichtbar
  und schreibbar.
- Ohne gesetzten Mandanten (Plattform-Admin, Hintergrundjobs, Worker, Abgabebox, Anmeldung,
  öffentliche Links, Migrationen) gilt die Policy nicht - diese Pfade arbeiten bewusst
  mandantenübergreifend und prüfen selbst.
- Geteilte Fotoalben: Mitglieder eines gemeinsamen Albums (Besitzer und angenommene Partner)
  sehen Album, Freigaben, Fotos, Galerie-Einträge, Album-Links und Kontonamen der anderen
  Mitglieder (photo_album_share_service.py); offen Eingeladene sehen nur das Album selbst. Die Hilfsfunktionen dafür sind
  SECURITY DEFINER, damit sich die Policies nicht gegenseitig rekursiv auswerten.
- Ausgenommen (kein RLS): audit_log, system_error_log, tenant_charge (nur Plattform, Schreiben
  in Fehlerpfaden darf nie scheitern) und tenant_domain (öffentliche DNS-Daten,
  mandantenübergreifende Eindeutigkeitsprüfung).

Superuser (Migrationen, Restore) umgehen RLS ohnehin; die Rollen hocx_abgabebox und
hocx_photo_worker setzen keinen Mandanten und sind wie bisher über Spaltenrechte begrenzt.

Revision ID: 0132_tenant_rls
Revises: 0131_todo_tenant_id
Create Date: 2026-10-19
"""

from alembic import op

revision = "0132_tenant_rls"
down_revision = "0131_todo_tenant_id"
branch_labels = None
depends_on = None

POLICY = "tenant_isolation"
READ_POLICY = "tenant_isolation_read"

# Nur eigene Zeilen (bzw. alle, solange kein Mandant gesetzt ist).
OWN_TABLES = (
    "calendar_feed",
    "cycle_config",
    "document",
    "document_asset",
    "document_brand",
    "document_component",
    "document_export",
    "document_job",
    "document_recipe_legacy",
    "document_registry",
    "document_style_legacy",
    "document_template_assignment",
    "element_definition",
    "event",
    "finance_account",
    "fine_tariff",
    "gallery_upload_job",
    "group_entity",
    "identity_verification_request",
    "leader",
    "list_definition",
    "photo_analysis_job",
    "protocol",
    "protocol_todo",
    "submission_assignment",
    "submission_link",
    "table_snapshot",
    "task_package",
    "template",
    "tenant_feature",
    "tenant_storage_package",
    "user_protocol_access",
    "user_protocol_template_preference",
    "user_template_access",
    "word_import_document",
    "word_import_profile",
    "word_import_suggestion_outcome",
)

SCOPE = "(SELECT public.hocx_rls_tenant())"
BASE = f"({SCOPE} IS NULL OR tenant_id = {SCOPE})"
# "= ANY (<Unterabfrage>)" würde Zeile für Zeile vergleichen; der Cast macht daraus ein Array, das
# PostgreSQL als InitPlan nur einmal je Abfrage auswertet.
PARTNERS = "tenant_id = ANY ((SELECT public.hocx_rls_partner_tenants())::bigint[])"
ALBUM_OWNER = f"public.hocx_rls_album_owner(album_id) = {SCOPE}"

ACCEPTED_ALBUMS = "(SELECT public.hocx_rls_accepted_album_ids())::uuid[]"
SHARED_ALBUMS = "(SELECT public.hocx_rls_shared_album_ids())::uuid[]"

# Tabelle -> (Lesen, Schreiben). Lesen gilt für SELECT, Schreiben (INSERT/UPDATE/DELETE, auch als
# WITH CHECK für die neue Zeile) ist nie weiter als Lesen.
SPECIAL_TABLES = {
    # Systemvorlagen (tenant_id NULL) sind für alle lesbar, aber nicht von Mandanten änderbar.
    "document_template": (f"({BASE} OR tenant_id IS NULL)", BASE),
    # Eingeladene sehen das Album (Einladungsliste), angenommene Partner arbeiten darin mit.
    "photo_album": (
        f"({BASE} OR id = ANY ({SHARED_ALBUMS}))",
        f"({BASE} OR id = ANY ({ACCEPTED_ALBUMS}))",
    ),
    # tenant_id ist hier der eingeladene Partner. Der Album-Besitzer sieht und verwaltet seine
    # Einladungen; angenommene Partner sehen die Freigaben der anderen Partner (Standort-/Link-
    # Schalter, photo_album_share_service.location_shared_with), ändern aber nur ihre eigene.
    "photo_album_tenant_share": (
        f"({BASE} OR {ALBUM_OWNER} OR album_id = ANY ({ACCEPTED_ALBUMS}))",
        f"({BASE} OR {ALBUM_OWNER})",
    ),
    # Fotos und Galerie-Einträge der anderen Album-Mitglieder; ändern nur eigene.
    "stored_file": (f"({BASE} OR {PARTNERS})", BASE),
    "gallery_image": (f"({BASE} OR {PARTNERS})", BASE),
    # Kontonamen (z. B. "erstellt von") der Album-Mitglieder; ändern nur eigene.
    "app_user": (f"({BASE} OR {PARTNERS})", BASE),
    # Der Album-Besitzer sieht und widerruft auch Links, die ein Partner auf sein Album erstellt hat.
    "share_link": (f"({BASE} OR {ALBUM_OWNER})", f"({BASE} OR {ALBUM_OWNER})"),
}

FUNCTIONS = (
    """
    CREATE OR REPLACE FUNCTION public.hocx_rls_tenant() RETURNS bigint
    LANGUAGE sql STABLE PARALLEL SAFE
    AS $$ SELECT NULLIF(current_setting('app.tenant_id', true), '')::bigint $$
    """,
    # Fremde Alben, in denen der Mandant angenommener Partner ist.
    """
    CREATE OR REPLACE FUNCTION public.hocx_rls_accepted_album_ids() RETURNS uuid[]
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
    AS $$
        SELECT COALESCE(array_agg(album_id), '{}'::uuid[])
          FROM photo_album_tenant_share
         WHERE tenant_id = public.hocx_rls_tenant() AND status = 'accepted'
    $$
    """,
    # Mitglieder (Besitzer oder angenommene Partner) aller Alben, in denen der Mandant selbst
    # Mitglied ist - auch Partner untereinander sehen die Fotos des gemeinsamen Albums.
    """
    CREATE OR REPLACE FUNCTION public.hocx_rls_partner_tenants() RETURNS bigint[]
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
    AS $$
        WITH shared_albums AS (
            SELECT s.album_id
              FROM photo_album_tenant_share s JOIN photo_album a ON a.id = s.album_id
             WHERE s.status = 'accepted'
               AND (s.tenant_id = public.hocx_rls_tenant() OR a.tenant_id = public.hocx_rls_tenant())
        )
        SELECT COALESCE(array_agg(DISTINCT member), '{}'::bigint[]) FROM (
            SELECT a.tenant_id AS member FROM photo_album a WHERE a.id IN (SELECT album_id FROM shared_albums)
            UNION
            SELECT s.tenant_id FROM photo_album_tenant_share s
             WHERE s.status = 'accepted' AND s.album_id IN (SELECT album_id FROM shared_albums)
        ) members
    $$
    """,
    # Fremde Alben, zu denen der Mandant eingeladen ist (auch offen/abgelehnt: Einladungsliste).
    """
    CREATE OR REPLACE FUNCTION public.hocx_rls_shared_album_ids() RETURNS uuid[]
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
    AS $$
        SELECT COALESCE(array_agg(album_id), '{}'::uuid[])
          FROM photo_album_tenant_share WHERE tenant_id = public.hocx_rls_tenant()
    $$
    """,
    """
    CREATE OR REPLACE FUNCTION public.hocx_rls_album_owner(p_album_id uuid) RETURNS bigint
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
    AS $$ SELECT tenant_id FROM photo_album WHERE id = p_album_id $$
    """,
)

FUNCTION_SIGNATURES = (
    "hocx_rls_album_owner(uuid)",
    "hocx_rls_accepted_album_ids()",
    "hocx_rls_shared_album_ids()",
    "hocx_rls_partner_tenants()",
    "hocx_rls_tenant()",
)


def _policies() -> dict[str, tuple[str, str]]:
    return {**{table: (BASE, BASE) for table in OWN_TABLES}, **SPECIAL_TABLES}


def upgrade() -> None:
    for statement in FUNCTIONS:
        op.execute(statement)
    for signature in FUNCTION_SIGNATURES:
        op.execute(f"REVOKE ALL ON FUNCTION public.{signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION public.{signature} TO hocx_app, hocx_abgabebox, hocx_photo_worker")
    for table, (read, write) in _policies().items():
        op.execute(f"CREATE POLICY {POLICY} ON public.{table} FOR ALL USING {write} WITH CHECK {write}")
        if read != write:
            # Permissive Policies werden je Befehl ODER-verknüpft: SELECT sieht read ∪ write = read.
            op.execute(f"CREATE POLICY {READ_POLICY} ON public.{table} FOR SELECT USING {read}")
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    for table in _policies():
        op.execute(f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS {READ_POLICY} ON public.{table}")
        op.execute(f"DROP POLICY IF EXISTS {POLICY} ON public.{table}")
    for signature in FUNCTION_SIGNATURES:
        op.execute(f"DROP FUNCTION IF EXISTS public.{signature}")
