"""Row-Level-Security auch für Mandantendaten ohne eigene tenant_id (Untertabellen)

0132_tenant_rls schützt nur Tabellen mit tenant_id. Viele Mandantendaten hängen aber allein an
ihrer Elterntabelle: Traktanden, Blöcke und Texte eines Protokolls, Listeneinträge, Buchungen,
Bussen, Vorlagen-Elemente, Album-Einträge, Dokumentversionen ... Für sie fehlte das zweite
Sicherheitsnetz: eine Abfrage per ID ohne Mandantenfilter fand auch fremde Zeilen.

Jetzt gilt für hocx_app und hocx_photo_worker: eine Zeile ist sichtbar und änderbar, wenn ihre
Elternzeile sichtbar ist. Die RLS der Elterntabelle wirkt darin mit (auch ihre Ausnahmen, etwa für
gemeinsame Fotoalben), über mehrere Ebenen bis zur Tabelle mit tenant_id. Ohne gebundenen
Mandanten greift die Abkürzung am Anfang der Bedingung, die EXISTS-Prüfung entfällt dann.

Ausnahmen: user_mfa_factor prüft den Mandanten des Kontos direkt (app_user ist für Partner von
Fotoalben sichtbar, deren MFA-Faktoren aber nie), Faktoren von Plattform-Admins sind im
Mandanten-Kontext unsichtbar. Revisionen von Systemvorlagen sind lesbar, aber nur für eigene
Vorlagen schreibbar.

Für Untertabellen, die schon für die Abgabebox geschützt sind (0133_abgabebox_rls), ersetzt die
Eltern-Policy die bisher offene Policy der anderen Rollen.

Revision ID: 0134_child_table_rls
Revises: 0133_abgabebox_rls
Create Date: 2026-10-20
"""

from alembic import op

revision = "0134_child_table_rls"
down_revision = "0133_abgabebox_rls"
branch_labels = None
depends_on = None

ROLES = "hocx_app, hocx_photo_worker"
POLICY = "tenant_isolation"
READ_POLICY = "tenant_isolation_read"
OPEN_POLICY = "tenant_isolation_open"
UNSCOPED = "(SELECT public.hocx_rls_tenant()) IS NULL"

# Tabelle -> (Elterntabelle, Spalte der Tabelle, die auf parent.id zeigt)
CHILD_TABLES = {
    "attendance_fine": ("protocol", "protocol_id"),
    "attendance_fine_merged_duplicate": ("protocol", "protocol_id"),
    "document_brand_revision": ("document_brand", "brand_id"),
    "document_version": ("document", "document_id"),
    "document_extraction": ("document_version", "document_version_id"),
    "document_file": ("document_version", "document_version_id"),
    "event_cycle": ("event", "event_id"),
    "finance_transaction": ("finance_account", "account_id"),
    "list_entry": ("list_definition", "list_definition_id"),
    "photo_album_item": ("photo_album", "album_id"),
    "protocol_element": ("protocol", "protocol_id"),
    "protocol_element_block": ("protocol_element", "protocol_element_id"),
    "protocol_display_snapshot": ("protocol_element_block", "protocol_element_block_id"),
    "protocol_image": ("protocol_element_block", "protocol_element_block_id"),
    "protocol_text": ("protocol_element_block", "protocol_element_block_id"),
    "protocol_todo_assignee": ("protocol_todo", "protocol_todo_id"),
    "protocol_todo_file": ("protocol_todo", "protocol_todo_id"),
    "share_link_file": ("share_link", "share_link_id"),
    "submission_assignment_link": ("submission_assignment", "assignment_id"),
    "submission_upload": ("submission_assignment", "assignment_id"),
    "submission_upload_file": ("submission_upload", "upload_id"),
    "submission_upload_log": ("submission_assignment", "assignment_id"),
    "task_package_cycle": ("task_package", "task_package_id"),
    "task_package_item": ("task_package", "task_package_id"),
    "template_element": ("template", "template_id"),
    "template_element_block": ("template_element", "template_element_id"),
    "template_participant": ("template", "template_id"),
    "user_protocol_scroll": ("protocol", "protocol_id"),
}

# Bereits für die Abgabebox mit RLS versehen, bisher für die anderen Rollen offen.
ABGABEBOX_CHILD_TABLES = (
    "event_cycle",
    "list_entry",
    "submission_assignment_link",
    "submission_upload",
    "submission_upload_file",
    "submission_upload_log",
)


def _parent_visible(table: str, parent: str, column: str) -> str:
    return f"({UNSCOPED} OR EXISTS (SELECT 1 FROM public.{parent} p WHERE p.id = {table}.{column}))"


def _policies() -> dict[str, tuple[str, str]]:
    """Tabelle -> (Lesen, Schreiben)."""
    policies = {table: (_parent_visible(table, parent, column),) * 2 for table, (parent, column) in CHILD_TABLES.items()}
    own_template = (
        f"({UNSCOPED} OR EXISTS (SELECT 1 FROM public.document_template p "
        "WHERE p.id = document_template_revision.template_id AND p.tenant_id = (SELECT public.hocx_rls_tenant())))"
    )
    policies["document_template_revision"] = (_parent_visible("document_template_revision", "document_template", "template_id"), own_template)
    own_account = (
        f"({UNSCOPED} OR EXISTS (SELECT 1 FROM public.app_user p "
        "WHERE p.id = user_mfa_factor.user_id AND p.tenant_id = (SELECT public.hocx_rls_tenant())))"
    )
    policies["user_mfa_factor"] = (own_account, own_account)
    return policies


def upgrade() -> None:
    for table in ABGABEBOX_CHILD_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {OPEN_POLICY} ON public.{table}")
    for table, (read, write) in _policies().items():
        op.execute(f"CREATE POLICY {POLICY} ON public.{table} FOR ALL TO {ROLES} USING {write} WITH CHECK {write}")
        if read != write:
            op.execute(f"CREATE POLICY {READ_POLICY} ON public.{table} FOR SELECT TO {ROLES} USING {read}")
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    for table in _policies():
        op.execute(f"DROP POLICY IF EXISTS {READ_POLICY} ON public.{table}")
        op.execute(f"DROP POLICY IF EXISTS {POLICY} ON public.{table}")
        if table not in ABGABEBOX_CHILD_TABLES:
            op.execute(f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY")
    for table in ABGABEBOX_CHILD_TABLES:
        op.execute(f"CREATE POLICY {OPEN_POLICY} ON public.{table} FOR ALL TO {ROLES} USING (true) WITH CHECK (true)")
