"""Objektspeicher (S3) für alle persistenten Dateien: Profile, aktiver Speicher mit Generation
und Schreib-Fence, Objektregister, Änderungsjournal und Live-Migrationen.

Grundidee (ausführlich in docs-site/docs/technik/storage/architektur.md):

- storage_profile: beliebig viele Speicherziele (lokales Garage-S3, AWS, Hetzner, sonstige
  S3-kompatible Anbieter). Zugangsdaten nur verschlüsselt (Fernet, STORAGE_CREDENTIALS_KEY).
  Das eingebaute Profil "filesystem" steht für den bisherigen Bestand auf der Platte
  (Generation 0) und ist bis zur Erstmigration aktiv.
- storage_state: genau eine Zeile. Welches Profil in welcher Generation aktiv ist, plus das
  Schreib-Fence für den Cutover. Jeder persistente Schreibvorgang nimmt über
  storage_begin_write() einen FOR-SHARE-Lock auf diese Zeile - der Cutover (FOR UPDATE) wartet
  dadurch auf alle offenen Schreibtransaktionen und neue Schreiber warten bzw. sehen danach das
  Fence. So schreibt nach dem Umschalten garantiert kein Prozess mehr in die alte Quelle.
- Jede Migration schreibt in eine neue Generation (eigener Key-Präfix g<n>/ im Ziel). Alte Daten
  eines früher genutzten Ziels können darum nie unbemerkt wieder aktiv werden, und alte
  Generationen bleiben bis zu einer separaten, auditierten Bereinigung erhalten.
- storage_object/storage_change_outbox: Register aller Objekte und lückenloses Journal jeder
  Änderung, in derselben Transaktion wie die fachliche Änderung geschrieben
  (storage_register_write). Die Live-Migration holt damit Änderungen während des Kopierens nach;
  pro Key gewinnt immer der jüngste Eintrag, gelöschte Objekte tauchen nicht wieder auf.

Die eingeschränkten Rollen hocx_abgabebox und hocx_photo_worker bekommen nur EXECUTE auf
SECURITY-DEFINER-Funktionen (Muster aus 0105), kein DML auf die Tabellen.

Revision ID: 0113_object_storage
Revises: 0112_protocol_todos_snapshot
Create Date: 2026-10-14
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0113_object_storage"
down_revision = "0112_protocol_todos_snapshot"
branch_labels = None
depends_on = None

MIGRATION_STATES = (
    "pending", "preflight", "awaiting_confirmation", "inventory", "copying", "catching_up", "verifying",
    "ready_for_cutover", "cutting_over", "observing", "completed", "paused", "retrying", "failed",
    "cancelled", "rollback_required",
)
TERMINAL_MIGRATION_STATES = ("completed", "failed", "cancelled")
OBJECT_STATES = ("pending", "copying", "copied", "verified", "failed", "dead", "deleted")

_FUNCTIONS = {
    "storage_begin_write()": "hocx_app, hocx_abgabebox",
    "storage_register_write(text, text, text, bigint, text, text, bigint)": "hocx_app, hocx_abgabebox",
    "storage_active_config(text)": "hocx_app, hocx_abgabebox, hocx_photo_worker",
    "storage_usage_bytes(text, text)": "hocx_app, hocx_abgabebox",
    "storage_local_s3_decision()": "hocx_app",
}


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.create_table(
        "storage_profile",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.Text(), nullable=False, unique=True),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("endpoint_url", sa.Text(), nullable=True),
        sa.Column("region", sa.Text(), nullable=True),
        sa.Column("bucket", sa.Text(), nullable=True),
        # Eigener Bucket für die öffentlich erreichbare Abgabebox (eigene, eingeschränkte
        # Zugangsdaten möglich). Leer = derselbe Bucket wie das Haupt-Backend.
        sa.Column("abgabebox_bucket", sa.Text(), nullable=True),
        sa.Column("prefix", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("addressing_style", sa.Text(), nullable=False, server_default=sa.text("'auto'")),
        sa.Column("access_key_enc", sa.Text(), nullable=True),
        sa.Column("secret_key_enc", sa.Text(), nullable=True),
        sa.Column("restricted_access_key_enc", sa.Text(), nullable=True),
        sa.Column("restricted_secret_key_enc", sa.Text(), nullable=True),
        sa.Column("tls_verify", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("ca_bundle_pem", sa.Text(), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_builtin", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        # Erhöht sich bei jeder Änderung; eine laufende Migration merkt sich die Version und
        # bricht ab, wenn sich Quelle oder Ziel unter ihr ändern.
        sa.Column("config_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("last_test_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_test_ok", sa.Boolean(), nullable=True),
        sa.Column("last_test_error", sa.Text(), nullable=True),
        sa.Column("created_by_email", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint(
            "provider IN ('filesystem', 'garage_local', 'aws_s3', 'hetzner', 's3_compatible')",
            name="ck_storage_profile_provider",
        ),
        sa.CheckConstraint("addressing_style IN ('auto', 'path', 'virtual')", name="ck_storage_profile_addressing"),
        sa.CheckConstraint("provider = 'filesystem' OR bucket IS NOT NULL", name="ck_storage_profile_bucket"),
        sa.CheckConstraint("prefix !~ '(^/|/$|//|\\.\\.)'", name="ck_storage_profile_prefix"),
    )
    # Höchstens ein eingebautes Dateisystem-Profil.
    op.create_index(
        "uq_storage_profile_filesystem", "storage_profile", ["provider"], unique=True,
        postgresql_where=sa.text("provider = 'filesystem'"),
    )

    op.create_table(
        "storage_state",
        sa.Column("id", sa.SmallInteger(), primary_key=True),
        sa.Column("active_profile_id", sa.BigInteger(), sa.ForeignKey("storage_profile.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("active_generation", sa.BigInteger(), nullable=False),
        sa.Column("write_fenced", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("fence_reason", sa.Text(), nullable=True),
        sa.Column("fence_token", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("fenced_at", sa.DateTime(timezone=True), nullable=True),
        # Admin-Anforderung "lokales S3 bereitstellen" (z. B. für Verbindungstest vor einer
        # Rückmigration) - der Host-Controller startet den Dienst bis zu diesem Zeitpunkt.
        sa.Column("local_s3_requested_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint("id = 1", name="ck_storage_state_singleton"),
    )

    op.create_table(
        "storage_generation",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("profile_id", sa.BigInteger(), sa.ForeignKey("storage_profile.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("generation", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("migration_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("object_count", sa.BigInteger(), nullable=True),
        sa.Column("total_bytes", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        # Rückfallfrist: bis dahin bleibt eine abgelöste Generation garantiert unangetastet.
        sa.Column("retain_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("purge_requested_by", sa.Text(), nullable=True),
        sa.Column("purge_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("purge_error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('preparing', 'active', 'retained', 'abandoned', 'purge_requested', 'purging', 'purged')",
            name="ck_storage_generation_status",
        ),
    )
    op.create_index(
        "uq_storage_generation_active", "storage_generation", ["status"], unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "storage_object",
        sa.Column("namespace", sa.Text(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("sha256", sa.Text(), nullable=True),
        sa.Column("content_type", sa.Text(), nullable=True),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default=sa.text("1")),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'active'")),
        sa.Column("generation", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("namespace", "key", name="pk_storage_object"),
        sa.CheckConstraint("namespace IN ('main', 'abgabebox')", name="ck_storage_object_namespace"),
        sa.CheckConstraint("status IN ('active', 'deleted')", name="ck_storage_object_status"),
    )
    op.create_index("idx_storage_object_status", "storage_object", ["namespace", "status"])

    op.create_table(
        "storage_change_outbox",
        sa.Column("seq", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("namespace", sa.Text(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("op", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("sha256", sa.Text(), nullable=True),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.Column("generation", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint("op IN ('put', 'delete')", name="ck_storage_change_outbox_op"),
    )
    op.create_index("idx_storage_change_outbox_key", "storage_change_outbox", ["namespace", "key", "seq"])
    op.create_index("idx_storage_change_outbox_created", "storage_change_outbox", ["created_at"])

    op.create_table(
        "storage_migration",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        # Zustand, in den "Fortsetzen" bzw. ein erfolgreicher Retry zurückkehrt.
        sa.Column("resume_state", sa.Text(), nullable=True),
        sa.Column("source_profile_id", sa.BigInteger(), sa.ForeignKey("storage_profile.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_generation", sa.BigInteger(), nullable=False),
        sa.Column("source_config_version", sa.Integer(), nullable=False),
        sa.Column("target_profile_id", sa.BigInteger(), sa.ForeignKey("storage_profile.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("target_generation", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("target_config_version", sa.Integer(), nullable=False),
        sa.Column("requested_by_email", sa.Text(), nullable=True),
        sa.Column("options", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("phase_started_at", sa.DateTime(timezone=True), nullable=True),
        # Worker-Lease mit Fencing-Token: jeder Schreibzugriff des Workers auf seine Migration
        # prüft das Token; ein Worker, der seine Lease verloren hat, schreibt nichts mehr.
        sa.Column("lease_owner", sa.Text(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fencing_token", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checkpoint_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checkpoint", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("snapshot_outbox_seq", sa.BigInteger(), nullable=True),
        sa.Column("applied_outbox_seq", sa.BigInteger(), nullable=True),
        sa.Column("total_objects", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("total_bytes", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("copied_objects", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("copied_bytes", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("verified_objects", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("failed_objects", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("throughput", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("pause_requested", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("retry_failed_requested", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("start_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("start_confirmed_by", sa.Text(), nullable=True),
        sa.Column("cutover_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cutover_confirmed_by", sa.Text(), nullable=True),
        sa.Column("cutover_committed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("maintenance_window_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("estimate", postgresql.JSONB(), nullable=True),
        sa.Column("report", postgresql.JSONB(), nullable=True),
        sa.CheckConstraint("kind IN ('initial', 'live')", name="ck_storage_migration_kind"),
        sa.CheckConstraint(f"state IN ({_in(MIGRATION_STATES)})", name="ck_storage_migration_state"),
        sa.CheckConstraint("source_profile_id <> target_profile_id OR source_generation <> target_generation", name="ck_storage_migration_distinct"),
    )
    # Höchstens eine nicht abgeschlossene Migration gleichzeitig - verhindert, dass zwei
    # Administratoren parallel denselben Datenbestand migrieren (auch bei gleichzeitigem Klick).
    op.execute(
        f"CREATE UNIQUE INDEX uq_storage_migration_open ON storage_migration ((true)) "
        f"WHERE state NOT IN ({_in(TERMINAL_MIGRATION_STATES)})"
    )
    op.create_index("idx_storage_migration_created", "storage_migration", ["created_at"])

    op.create_table(
        "storage_migration_object",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("migration_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("storage_migration.id", ondelete="CASCADE"), nullable=False),
        sa.Column("namespace", sa.Text(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("expected_size", sa.BigInteger(), nullable=True),
        sa.Column("expected_sha256", sa.Text(), nullable=True),
        sa.Column("expected_version", sa.BigInteger(), nullable=True),
        # 0 = aus der Inventur, sonst Sequenz des Journaleintrags, der diesen Stand festlegt.
        sa.Column("source_seq", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("referenced", sa.Boolean(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("copied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("migration_id", "namespace", "key", name="uq_storage_migration_object_key"),
        sa.CheckConstraint(f"status IN ({_in(OBJECT_STATES)})", name="ck_storage_migration_object_status"),
    )
    op.create_index("idx_storage_migration_object_status", "storage_migration_object", ["migration_id", "status", "id"])

    op.create_table(
        "storage_migration_event",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("migration_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("storage_migration.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("level", sa.Text(), nullable=False, server_default=sa.text("'info'")),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("actor_email", sa.Text(), nullable=True),
        sa.Column("from_state", sa.Text(), nullable=True),
        sa.Column("to_state", sa.Text(), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("details", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.CheckConstraint("level IN ('info', 'warning', 'error')", name="ck_storage_migration_event_level"),
    )
    op.create_index("idx_storage_migration_event_migration", "storage_migration_event", ["migration_id", "id"])

    # Bestand vor der Erstmigration: das bisherige Dateisystem als Generation 0.
    op.execute("""
        INSERT INTO storage_profile (name, provider, is_builtin, prefix)
        VALUES ('Lokales Dateisystem (bisheriger Bestand)', 'filesystem', true, '')
    """)
    op.execute("""
        INSERT INTO storage_state (id, active_profile_id, active_generation)
        SELECT 1, id, 0 FROM storage_profile WHERE provider = 'filesystem'
    """)
    op.execute("""
        INSERT INTO storage_generation (profile_id, generation, status, activated_at)
        SELECT id, 0, 'active', NOW() FROM storage_profile WHERE provider = 'filesystem'
    """)

    # --- Funktionen für Schreiber (Backend, Abgabebox) -------------------------------------
    op.execute(r"""
        CREATE FUNCTION public.storage_begin_write()
        RETURNS TABLE (profile_id bigint, generation bigint, fenced boolean, fence_reason text)
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
        BEGIN
          -- FOR SHARE: beliebig viele Schreiber gleichzeitig, aber der Cutover (FOR UPDATE)
          -- wartet auf alle offenen Schreibtransaktionen, und Schreiber, die nach ihm kommen,
          -- warten auf ihn. Der Lock gilt bis zum Ende der Transaktion des Aufrufers.
          RETURN QUERY
            SELECT s.active_profile_id, s.active_generation, s.write_fenced, s.fence_reason
            FROM public.storage_state s WHERE s.id = 1 FOR SHARE;
        END
        $$
    """)
    op.execute(r"""
        CREATE FUNCTION public.storage_register_write(
            p_namespace text, p_key text, p_op text, p_size bigint, p_sha256 text, p_content_type text,
            p_generation bigint
        ) RETURNS bigint
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
        DECLARE
          v_active_generation bigint;
          v_version bigint;
        BEGIN
          IF p_namespace NOT IN ('main', 'abgabebox') THEN
            RAISE EXCEPTION 'invalid storage namespace: %', p_namespace;
          END IF;
          IF p_key IS NULL OR length(p_key) = 0 OR length(p_key) > 1024 OR p_key ~ '[[:cntrl:]\\]'
             OR p_key ~ '(^/|//|(^|/)\.\.?(/|$))' THEN
            RAISE EXCEPTION 'invalid storage key';
          END IF;
          IF p_op NOT IN ('put', 'delete') THEN
            RAISE EXCEPTION 'invalid storage op: %', p_op;
          END IF;
          IF p_sha256 IS NOT NULL AND p_sha256 !~ '^[0-9a-f]{64}$' THEN
            RAISE EXCEPTION 'invalid sha256';
          END IF;
          -- Der Aufrufer muss vorher storage_begin_write() in derselben Transaktion aufgerufen
          -- haben; die Generation muss noch die aktive sein (sonst hat ein Cutover dazwischen
          -- stattgefunden und der Schreibvorgang landete in der falschen Quelle).
          SELECT s.active_generation INTO v_active_generation FROM public.storage_state s WHERE s.id = 1 FOR SHARE;
          IF v_active_generation <> p_generation THEN
            RAISE EXCEPTION 'HOCX_STORAGE_GENERATION_CHANGED' USING ERRCODE = '40001';
          END IF;

          INSERT INTO public.storage_object AS o (namespace, key, size_bytes, sha256, content_type, version, status, generation)
          VALUES (p_namespace, p_key, p_size, p_sha256, p_content_type, 1,
                  CASE WHEN p_op = 'put' THEN 'active' ELSE 'deleted' END, p_generation)
          ON CONFLICT (namespace, key) DO UPDATE SET
            size_bytes = CASE WHEN p_op = 'put' THEN EXCLUDED.size_bytes ELSE o.size_bytes END,
            sha256 = CASE WHEN p_op = 'put' THEN EXCLUDED.sha256 ELSE o.sha256 END,
            content_type = CASE WHEN p_op = 'put' THEN EXCLUDED.content_type ELSE o.content_type END,
            version = o.version + 1,
            status = EXCLUDED.status,
            generation = EXCLUDED.generation,
            updated_at = NOW()
          RETURNING o.version INTO v_version;

          INSERT INTO public.storage_change_outbox (namespace, key, op, size_bytes, sha256, version, generation)
          VALUES (p_namespace, p_key, p_op, p_size, p_sha256, v_version, p_generation);
          RETURN v_version;
        END
        $$
    """)
    # Aktive Konfiguration je Dienst. Die Abgabebox bekommt ihren eigenen Bucket und - falls
    # hinterlegt - die eingeschränkten Zugangsdaten, nie beide Schlüsselpaare.
    op.execute(r"""
        CREATE FUNCTION public.storage_active_config(p_service text)
        RETURNS TABLE (
          profile_id bigint, generation bigint, provider text, endpoint_url text, region text,
          bucket text, abgabebox_bucket text, prefix text, addressing_style text, access_key_enc text,
          secret_key_enc text, tls_verify boolean, ca_bundle_pem text, fenced boolean, config_version integer
        )
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
        BEGIN
          IF p_service NOT IN ('backend', 'abgabebox', 'photo-worker') THEN
            RAISE EXCEPTION 'invalid storage service: %', p_service;
          END IF;
          RETURN QUERY
            SELECT p.id, s.active_generation, p.provider, p.endpoint_url, p.region,
                   CASE WHEN p_service = 'abgabebox' THEN COALESCE(p.abgabebox_bucket, p.bucket) ELSE p.bucket END,
                   COALESCE(p.abgabebox_bucket, p.bucket),
                   p.prefix, p.addressing_style,
                   CASE WHEN p_service = 'abgabebox' AND p.restricted_access_key_enc IS NOT NULL
                        THEN p.restricted_access_key_enc ELSE p.access_key_enc END,
                   CASE WHEN p_service = 'abgabebox' AND p.restricted_secret_key_enc IS NOT NULL
                        THEN p.restricted_secret_key_enc ELSE p.secret_key_enc END,
                   p.tls_verify, p.ca_bundle_pem, s.write_fenced, p.config_version
            FROM public.storage_state s JOIN public.storage_profile p ON p.id = s.active_profile_id
            WHERE s.id = 1;
        END
        $$
    """)
    op.execute(r"""
        CREATE FUNCTION public.storage_usage_bytes(p_namespace text, p_prefix text) RETURNS bigint
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
          SELECT COALESCE(SUM(o.size_bytes), 0)::bigint FROM public.storage_object o
          WHERE o.namespace = p_namespace AND o.status = 'active'
            AND left(o.key, length(p_prefix)) = p_prefix
        $$
    """)
    # Entscheidungsgrundlage für den Host-seitigen Storage-Controller (scripts/storage_controller.sh):
    # darf der lokale S3-Container gestoppt werden? Bewusst konservativ - im Zweifel "benötigt".
    op.execute(r"""
        CREATE FUNCTION public.storage_local_s3_decision()
        RETURNS TABLE (needed boolean, reason text)
        LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
        DECLARE
          v_local_ids bigint[];
        BEGIN
          SELECT array_agg(id) INTO v_local_ids FROM public.storage_profile WHERE provider = 'garage_local';
          IF v_local_ids IS NULL THEN
            RETURN QUERY SELECT false, 'no_local_profile'; RETURN;
          END IF;
          IF EXISTS (SELECT 1 FROM public.storage_state WHERE active_profile_id = ANY (v_local_ids)) THEN
            RETURN QUERY SELECT true, 'active'; RETURN;
          END IF;
          -- Vor der Erstmigration ist das lokale S3 das vorgesehene Ziel und muss bereitstehen.
          IF EXISTS (SELECT 1 FROM public.storage_state s JOIN public.storage_profile p ON p.id = s.active_profile_id
                     WHERE p.provider = 'filesystem') THEN
            RETURN QUERY SELECT true, 'initial_target'; RETURN;
          END IF;
          IF EXISTS (SELECT 1 FROM public.storage_state WHERE local_s3_requested_until > NOW()) THEN
            RETURN QUERY SELECT true, 'requested'; RETURN;
          END IF;
          IF EXISTS (SELECT 1 FROM public.storage_migration
                     WHERE state NOT IN ('completed', 'failed', 'cancelled')
                       AND (source_profile_id = ANY (v_local_ids) OR target_profile_id = ANY (v_local_ids))) THEN
            RETURN QUERY SELECT true, 'migration'; RETURN;
          END IF;
          -- Abgeschlossene Migration noch in der Beobachtungs-/Rückfallphase oder nicht
          -- vollständig verifiziert: die alte lokale Quelle muss erreichbar bleiben.
          IF EXISTS (SELECT 1 FROM public.storage_generation
                     WHERE profile_id = ANY (v_local_ids) AND status = 'retained'
                       AND (retain_until IS NULL OR retain_until > NOW())) THEN
            RETURN QUERY SELECT true, 'fallback_period'; RETURN;
          END IF;
          IF EXISTS (SELECT 1 FROM public.storage_generation
                     WHERE profile_id = ANY (v_local_ids) AND status IN ('preparing', 'purge_requested', 'purging')) THEN
            RETURN QUERY SELECT true, 'pending_operation'; RETURN;
          END IF;
          IF EXISTS (SELECT 1 FROM public.storage_migration m
                     WHERE m.source_profile_id = ANY (v_local_ids) AND m.state = 'completed'
                       AND EXISTS (SELECT 1 FROM public.storage_migration_object o
                                   WHERE o.migration_id = m.id AND o.status NOT IN ('verified', 'deleted'))) THEN
            RETURN QUERY SELECT true, 'unverified_objects'; RETURN;
          END IF;
          RETURN QUERY SELECT false, 'not_needed';
        END
        $$
    """)
    for signature, roles in _FUNCTIONS.items():
        op.execute(f"REVOKE ALL ON FUNCTION public.{signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION public.{signature} TO {roles}")
    # Foto-Worker muss Abgabebox-Bilder dem Namespace "abgabebox" zuordnen können (nur diese Spalte).
    op.execute("GRANT SELECT (stored_file_id) ON TABLE public.submission_upload_file TO hocx_photo_worker")


def downgrade() -> None:
    op.execute("REVOKE SELECT (stored_file_id) ON TABLE public.submission_upload_file FROM hocx_photo_worker")
    for signature in _FUNCTIONS:
        op.execute(f"DROP FUNCTION IF EXISTS public.{signature}")
    op.drop_table("storage_migration_event")
    op.drop_table("storage_migration_object")
    op.drop_table("storage_migration")
    op.drop_table("storage_change_outbox")
    op.drop_table("storage_object")
    op.drop_table("storage_generation")
    op.drop_table("storage_state")
    op.drop_table("storage_profile")
