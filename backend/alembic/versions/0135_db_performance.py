"""Indizes für Fremdschlüssel und Timeouts der Laufzeitrollen

Datenbank-Optimierung nach dem Security-Audit release/1.2.0:

- **Indizes:** Fremdschlüssel ohne Index zwingen PostgreSQL beim Löschen der Elternzeile
  (ON DELETE SET NULL/CASCADE) zu einem vollständigen Scan der Kindtabelle - beim Löschen eines
  Kontos oder Mandanten für jede der vielen created_by/updated_by-Spalten. Einige werden zudem
  direkt abgefragt (Auto-Alben je Zyklus/Abgabe, Tabellen-Snapshots je Zyklus, Zuordnung von
  Dokumentvorlagen). Teilindizes (WHERE ... IS NOT NULL) halten die meist leeren Spalten klein.
- **Timeouts:** Die öffentliche Abgabebox und der Fotoworker hatten kein statement_timeout, keine
  Rolle ein idle_in_transaction_session_timeout - eine hängengebliebene Transaktion hielt Sperren
  und eine Verbindung bis zum Neustart. Die Werte sind grosszügig (Sicherheitsnetz, keine enge
  Grenze); app/backup/restore_core.py::ensure_app_roles setzt sie nach einem Full-Restore gleich.

Revision ID: 0135_db_performance
Revises: 0134_child_table_rls
Create Date: 2026-10-20
"""

from alembic import op

revision = "0135_db_performance"
down_revision = "0134_child_table_rls"
branch_labels = None
depends_on = None

# (Tabelle, Spalte, nur Teilindex für gesetzte Werte)
FOREIGN_KEY_INDEXES = (
    # Verweise auf app_user (Konto löschen: SET NULL)
    ("document_asset", "created_by", True),
    ("document_brand", "created_by", True),
    ("document_brand", "updated_by", True),
    ("document_brand_revision", "created_by", True),
    ("document_component", "created_by", True),
    ("document_component", "updated_by", True),
    ("document_export", "created_by", True),
    ("document_registry", "created_by", True),
    ("document_template", "created_by", True),
    ("document_template", "updated_by", True),
    ("document_template_assignment", "created_by", True),
    ("document_template_revision", "created_by", True),
    ("document_template_revision", "published_by", True),
    ("document_template_revision", "updated_by", True),
    ("document_version", "created_by", True),
    ("gallery_image", "created_by", True),
    ("gallery_upload_job", "requested_by", True),
    ("identity_verification_request", "requested_by", True),
    ("photo_album_tenant_share", "invited_by", True),
    ("photo_album_tenant_share", "responded_by", True),
    ("photo_analysis_job", "requested_by", True),
    ("share_link", "created_by", True),
    ("stored_file", "estimated_taken_set_by", True),
    ("table_snapshot", "edited_by", True),
    # Abfragen und Kaskaden innerhalb eines Mandanten
    ("photo_album", "cycle_config_id", True),
    ("photo_album", "submission_assignment_id", True),
    ("table_snapshot", "cycle_config_id", False),
    ("document_template_assignment", "protocol_template_id", True),
    ("document_template_assignment", "document_template_id", True),
    ("document_template_assignment", "brand_id", True),
    ("document_export", "template_id", True),
    ("document_export", "template_revision_id", True),
    ("document_export", "brand_revision_id", True),
    ("document_template", "brand_id", True),
    ("document_template", "source_template_id", True),
    ("document_template", "published_revision_id", True),
    ("document_template", "source_revision_id", True),
    ("document_template_revision", "brand_revision_id", True),
    ("document", "current_version_id", True),
    ("gallery_upload_job", "upload_assignment_id", True),
    ("gallery_upload_job", "upload_cycle_config_id", True),
    ("gallery_upload_job", "upload_event_id", True),
    ("user_protocol_template_preference", "template_id", True),
)

# Rolle -> {Einstellung: Wert}; hocx_app hat statement_timeout schon seit 0001.
ROLE_SETTINGS = {
    "hocx_app": {"idle_in_transaction_session_timeout": "30min"},
    "hocx_abgabebox": {"statement_timeout": "30s", "idle_in_transaction_session_timeout": "15min"},
    "hocx_photo_worker": {"statement_timeout": "60s", "idle_in_transaction_session_timeout": "15min"},
}


def _index_name(table: str, column: str) -> str:
    return f"idx_{table}_{column}"[:63]


def upgrade() -> None:
    for table, column, partial in FOREIGN_KEY_INDEXES:
        where = f" WHERE {column} IS NOT NULL" if partial else ""
        op.execute(f"CREATE INDEX IF NOT EXISTS {_index_name(table, column)} ON public.{table} ({column}){where}")
    for role, settings in ROLE_SETTINGS.items():
        for name, value in settings.items():
            op.execute(f"ALTER ROLE {role} SET {name} = '{value}'")


def downgrade() -> None:
    for role, settings in ROLE_SETTINGS.items():
        for name in settings:
            if not (role == "hocx_app" and name == "statement_timeout"):
                op.execute(f"ALTER ROLE {role} RESET {name}")
    for table, column, _partial in FOREIGN_KEY_INDEXES:
        op.execute(f"DROP INDEX IF EXISTS public.{_index_name(table, column)}")
