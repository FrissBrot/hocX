"""Datei-Import P1: Cloud-Verbindungen (OAuth) und API-Quellen (Plan «Cloud-Datei-Importer», hocX 1.6).

- ``import_connection``: Verbindung einer Person zu einem Cloud-Konto (Microsoft, später Google,
  Dropbox, WebDAV). Tokens nur verschlüsselt (``CLOUD_IMPORT_TOKEN_KEY``, MultiFernet,
  services/cloud_import/token_crypto.py), nie im Klartext, nie in Logs. ``tenant_id`` NOT NULL,
  RLS ``tenant_isolation`` wie 0230. Gelöscht bei Auftragsende bzw. nach ``purge_after``.
- ``import_job``: Quelle je Anbieter (alle geplanten Werte schon jetzt, damit weitere
  Adapter ohne eigene Migration dazukommen), ``connection_id`` (zusammengesetzter FK im selben
  Mandanten, SET NULL), Auswahl (``selection``), Stand des Auflistens (``listing_state``),
  Drosselung (``not_before``), neue Status ``listing`` und ``needs_reauth`` (beide zählen als
  aktiver Auftrag: weiter höchstens ein Import je Mandant, E-5).
- ``import_item``: Kennungen beim Anbieter (``provider_item_id``, ``provider_drive_id``,
  ``provider_hash``, ``provider_mime``) für Download und Wiederaufnahme; ``next_attempt_at`` für
  Wiederholungen mit Wartezeit.

Revision ID: 0281_cloud_import_connections
Revises: 0280_auth_event_subject_index
Create Date: 2026-11-25
"""

from __future__ import annotations

from alembic import op

revision = "0281_cloud_import_connections"
down_revision = "0280_auth_event_subject_index"
branch_labels = None
depends_on = None

SCOPE = "(SELECT public.hocx_rls_tenant())"
BASE = f"({SCOPE} IS NULL OR tenant_id = {SCOPE})"

PROVIDERS = "('microsoft', 'google_drive', 'google_photos', 'dropbox', 'webdav')"
SOURCES_OLD = "('zip', 'folder')"
SOURCES_NEW = "('zip', 'folder', 'microsoft', 'google_drive', 'google_photos', 'dropbox', 'webdav')"
STATUSES_OLD = "('draft', 'ready', 'queued', 'running', 'cancel_requested', 'cancelled', 'done', 'failed')"
STATUSES_NEW = (
    "('draft', 'listing', 'ready', 'queued', 'running', 'needs_reauth', 'cancel_requested', 'cancelled', 'done', 'failed')"
)
ACTIVE_OLD = "('draft', 'ready', 'queued', 'running', 'cancel_requested')"
ACTIVE_NEW = "('draft', 'listing', 'ready', 'queued', 'running', 'needs_reauth', 'cancel_requested')"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE import_connection (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            tenant_id bigint NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            user_id bigint NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
            provider text NOT NULL,
            status text NOT NULL DEFAULT 'active',
            account_label text,
            account_kind text,
            account_tenant_id text,
            account_subject text,
            granted_scopes text NOT NULL DEFAULT '',
            access_token_encrypted text,
            refresh_token_encrypted text,
            access_expires_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            last_used_at timestamptz,
            purge_after timestamptz NOT NULL,
            CONSTRAINT ck_import_connection_provider CHECK (provider IN {PROVIDERS}),
            CONSTRAINT ck_import_connection_status CHECK (status IN ('active', 'needs_reauth')),
            CONSTRAINT uq_import_connection_tenant_id UNIQUE (tenant_id, id)
        )
        """  # sql-ok: feste Werteliste aus dem Code
    )
    op.execute("CREATE INDEX idx_import_connection_user ON import_connection (tenant_id, user_id)")
    op.execute("CREATE INDEX idx_import_connection_purge ON import_connection (purge_after)")
    op.execute(f"CREATE POLICY tenant_isolation ON public.import_connection FOR ALL USING {BASE} WITH CHECK {BASE}")  # sql-ok: feste Policy
    op.execute("ALTER TABLE public.import_connection ENABLE ROW LEVEL SECURITY")

    op.execute("ALTER TABLE import_job ADD COLUMN connection_id uuid")
    op.execute("ALTER TABLE import_job ADD COLUMN selection jsonb NOT NULL DEFAULT '[]'::jsonb")
    op.execute("ALTER TABLE import_job ADD COLUMN listing_state jsonb NOT NULL DEFAULT '{}'::jsonb")
    op.execute("ALTER TABLE import_job ADD COLUMN not_before timestamptz")
    op.execute("ALTER TABLE import_job ADD COLUMN reauth_since timestamptz")
    # Verbindung und Auftrag liegen immer im selben Mandanten; Löschen der Verbindung (Tokens weg)
    # lässt den Auftrag samt Bericht stehen.
    op.execute(
        "ALTER TABLE import_job ADD CONSTRAINT fk_import_job_connection FOREIGN KEY (tenant_id, connection_id) "
        "REFERENCES import_connection (tenant_id, id) ON DELETE SET NULL (connection_id)"
    )
    op.execute("CREATE INDEX idx_import_job_connection ON import_job (connection_id) WHERE connection_id IS NOT NULL")
    op.execute("ALTER TABLE import_job DROP CONSTRAINT ck_import_job_source")
    op.execute(f"ALTER TABLE import_job ADD CONSTRAINT ck_import_job_source CHECK (source IN {SOURCES_NEW})")  # sql-ok: feste Werteliste
    op.execute("ALTER TABLE import_job DROP CONSTRAINT ck_import_job_status")
    op.execute(f"ALTER TABLE import_job ADD CONSTRAINT ck_import_job_status CHECK (status IN {STATUSES_NEW})")  # sql-ok: feste Werteliste
    op.execute("DROP INDEX uq_import_job_one_active")
    op.execute(f"CREATE UNIQUE INDEX uq_import_job_one_active ON import_job (tenant_id) WHERE status IN {ACTIVE_NEW}")  # sql-ok: feste Werteliste

    op.execute("ALTER TABLE import_item ADD COLUMN provider_item_id text")
    op.execute("ALTER TABLE import_item ADD COLUMN provider_drive_id text")
    op.execute("ALTER TABLE import_item ADD COLUMN provider_hash text")
    op.execute("ALTER TABLE import_item ADD COLUMN provider_mime text")
    op.execute("ALTER TABLE import_item ADD COLUMN next_attempt_at timestamptz")


def downgrade() -> None:
    op.execute("DELETE FROM import_job WHERE source NOT IN ('zip', 'folder')")
    op.execute("UPDATE import_job SET status = 'failed' WHERE status IN ('listing', 'needs_reauth')")
    for column in ("provider_item_id", "provider_drive_id", "provider_hash", "provider_mime", "next_attempt_at"):
        op.execute(f"ALTER TABLE import_item DROP COLUMN IF EXISTS {column}")  # sql-ok: feste Spaltennamen
    op.execute("DROP INDEX IF EXISTS uq_import_job_one_active")
    op.execute(f"CREATE UNIQUE INDEX uq_import_job_one_active ON import_job (tenant_id) WHERE status IN {ACTIVE_OLD}")  # sql-ok: feste Werteliste
    op.execute("ALTER TABLE import_job DROP CONSTRAINT ck_import_job_status")
    op.execute(f"ALTER TABLE import_job ADD CONSTRAINT ck_import_job_status CHECK (status IN {STATUSES_OLD})")  # sql-ok: feste Werteliste
    op.execute("ALTER TABLE import_job DROP CONSTRAINT ck_import_job_source")
    op.execute(f"ALTER TABLE import_job ADD CONSTRAINT ck_import_job_source CHECK (source IN {SOURCES_OLD})")  # sql-ok: feste Werteliste
    op.execute("ALTER TABLE import_job DROP CONSTRAINT IF EXISTS fk_import_job_connection")
    for column in ("connection_id", "selection", "listing_state", "not_before", "reauth_since"):
        op.execute(f"ALTER TABLE import_job DROP COLUMN IF EXISTS {column}")  # sql-ok: feste Spaltennamen
    op.execute("DROP TABLE IF EXISTS import_connection")
