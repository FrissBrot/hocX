"""Backup- und Restore-System (BorgBackup, Hetzner Storage Box) - siehe
docs-site/docs/technik/backup/architektur.md.

- backup_settings: eine Zeile mit Zeitplan, Retention, Prüfintervallen, Benachrichtigungsmodus
  und dem zuletzt vom Worker ermittelten Repository-Status. Keine Secrets - die liegen nur als
  Docker-Secrets beim backup-worker.
- backup_job: persistente Aufträge (Backup, Prüfung, Restore-Test, Retention) mit Worker-Lease,
  Fencing-Token, Heartbeat und Fortschritt. Höchstens ein offener Backup-Auftrag gleichzeitig.
- backup_set: Index der Wiederherstellungspunkte (rp-Archive im Borg-Repository). Die Quelle der
  Wahrheit bleibt das Repository; der Worker gleicht den Index regelmässig dagegen ab.
- backup_pool_archive / backup_content: inhaltsadressierter Objektindex (SHA-256 -> Pool-Archiv)
  für die inkrementelle Sicherung ohne erneuten Download unveränderter Objekte.
- backup_restore_job: Voll-Restore und Mandanten-Restore als Kopie, mit Plan, Bestätigung
  (inkl. frischer TOTP-Prüfung) und Lease.
- backup_event: Verlauf aller Aufträge (Audit der Abläufe; Admin-Aktionen zusätzlich audit_log).
- storage_state.backup_hold_*: Backup-Hold für die Konsistenz zwischen Dump und Objekten.
  Solange ein Hold auf der aktiven Generation liegt, sichern Schreiber den bisherigen Inhalt
  eines registrierten Objekts vor dem Löschen/Überschreiben (Copy-on-Write) - die Abfrage dafür
  ist storage_backup_hold(), damit auch die eingeschränkte Rolle hocx_abgabebox mitmacht.

Revision ID: 0115_backup_system
Revises: 0114_maintenance
Create Date: 2026-10-15
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0115_backup_system"
down_revision = "0114_maintenance"
branch_labels = None
depends_on = None

JOB_KINDS = ("backup", "verify", "restore_test", "retention")
JOB_TRIGGERS = ("schedule", "manual", "pre_restore", "pre_deploy", "cli")
JOB_STATES = ("queued", "preparing", "running", "verifying", "completed", "partial", "failed", "cancelled", "interrupted")
OPEN_JOB_STATES = ("queued", "preparing", "running", "verifying")
SET_STATES = ("completed", "partial", "failed", "invalid", "pruned")
RESTORE_KINDS = ("full", "tenant_copy")
RESTORE_STATES = (
    "queued", "preparing", "running", "verifying", "cutover", "completed", "failed", "cancelled", "interrupted", "rolled_back",
)
OPEN_RESTORE_STATES = ("queued", "preparing", "running", "verifying", "cutover")

_FUNCTIONS = {
    "storage_backup_hold(text, text, bigint)": "hocx_app, hocx_abgabebox",
}


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _lease_columns() -> list[sa.Column]:
    return [
        sa.Column("lease_owner", sa.Text(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fencing_token", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("progress", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("checkpoint", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    ]


def upgrade() -> None:
    op.create_table(
        "backup_settings",
        sa.Column("id", sa.SmallInteger(), primary_key=True),
        sa.Column("schedule_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("interval_hours", sa.Integer(), nullable=False, server_default=sa.text("6")),
        # Versatz der Planläufe gegenüber Mitternacht UTC (z. B. 30 = 00:30, 06:30, ...).
        sa.Column("schedule_offset_minutes", sa.Integer(), nullable=False, server_default=sa.text("15")),
        sa.Column("keep_within_days", sa.Integer(), nullable=False, server_default=sa.text("14")),
        sa.Column("keep_daily", sa.Integer(), nullable=False, server_default=sa.text("14")),
        sa.Column("keep_weekly", sa.Integer(), nullable=False, server_default=sa.text("8")),
        sa.Column("keep_monthly", sa.Integer(), nullable=False, server_default=sa.text("12")),
        sa.Column("verify_interval_hours", sa.Integer(), nullable=False, server_default=sa.text("168")),
        sa.Column("verify_sample_objects", sa.Integer(), nullable=False, server_default=sa.text("200")),
        sa.Column("restore_test_interval_days", sa.Integer(), nullable=False, server_default=sa.text("30")),
        # off = nur Probleme melden, daily = tägliche Zusammenfassung, each = jede Sicherung.
        sa.Column("success_notification", sa.Text(), nullable=False, server_default=sa.text("'daily'")),
        sa.Column("last_daily_summary_at", sa.DateTime(timezone=True), nullable=True),
        # Vom Worker gemeldeter Zustand (Erreichbarkeit, Repository-ID, Borg-Version, Grössen,
        # Kapazität, Fehler). Nie Secrets.
        sa.Column("repository_status", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("repository_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worker_config", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_by_email", sa.Text(), nullable=True),
        sa.CheckConstraint("id = 1", name="ck_backup_settings_singleton"),
        sa.CheckConstraint("interval_hours BETWEEN 1 AND 168", name="ck_backup_settings_interval"),
        sa.CheckConstraint("schedule_offset_minutes BETWEEN 0 AND 1439", name="ck_backup_settings_offset"),
        sa.CheckConstraint(
            "keep_within_days BETWEEN 0 AND 3650 AND keep_daily BETWEEN 0 AND 3650 AND keep_weekly BETWEEN 0 AND 520 "
            "AND keep_monthly BETWEEN 0 AND 240 AND (keep_within_days + keep_daily + keep_weekly + keep_monthly) > 0",
            name="ck_backup_settings_retention",
        ),
        sa.CheckConstraint("verify_interval_hours BETWEEN 1 AND 8760", name="ck_backup_settings_verify_interval"),
        sa.CheckConstraint("verify_sample_objects BETWEEN 0 AND 100000", name="ck_backup_settings_verify_sample"),
        sa.CheckConstraint("restore_test_interval_days BETWEEN 1 AND 365", name="ck_backup_settings_restore_test"),
        sa.CheckConstraint("success_notification IN ('off', 'daily', 'each')", name="ck_backup_settings_success_notification"),
    )
    op.execute("INSERT INTO backup_settings (id) VALUES (1)")

    op.create_table(
        "backup_set",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("archive_name", sa.Text(), nullable=False, unique=True),
        sa.Column("archive_id", sa.Text(), nullable=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("trigger", sa.Text(), nullable=False, server_default=sa.text("'schedule'")),
        # Nie durch die Retention entfernen (Rettungspunkt vor Restore, vor Deploy, manuell).
        sa.Column("protected", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("protected_reason", sa.Text(), nullable=True),
        sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("app_version", sa.Text(), nullable=True),
        sa.Column("alembic_revision", sa.Text(), nullable=True),
        sa.Column("pg_server_version", sa.Text(), nullable=True),
        sa.Column("profile_name", sa.Text(), nullable=True),
        sa.Column("profile_provider", sa.Text(), nullable=True),
        sa.Column("generation", sa.BigInteger(), nullable=True),
        sa.Column("outbox_seq", sa.BigInteger(), nullable=True),
        sa.Column("db_dump_bytes", sa.BigInteger(), nullable=True),
        sa.Column("db_dump_sha256", sa.Text(), nullable=True),
        sa.Column("manifest_sha256", sa.Text(), nullable=True),
        sa.Column("object_count", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("object_bytes", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("new_object_count", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("new_object_bytes", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("deduplicated_bytes", sa.BigInteger(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("pool_archives", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("tenants", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("warnings", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("verify_state", sa.Text(), nullable=False, server_default=sa.text("'unverified'")),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verify_details", postgresql.JSONB(), nullable=True),
        sa.Column("restore_test_state", sa.Text(), nullable=False, server_default=sa.text("'untested'")),
        sa.Column("restore_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("restore_test_details", postgresql.JSONB(), nullable=True),
        sa.Column("pruned_at", sa.DateTime(timezone=True), nullable=True),
        # True, wenn der Eintrag beim Abgleich aus dem Repository rekonstruiert wurde.
        sa.Column("reconstructed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint(f"state IN ({_in(SET_STATES)})", name="ck_backup_set_state"),
        sa.CheckConstraint(f"trigger IN ({_in(JOB_TRIGGERS)})", name="ck_backup_set_trigger"),
        sa.CheckConstraint("verify_state IN ('unverified', 'verified', 'failed')", name="ck_backup_set_verify_state"),
        sa.CheckConstraint("restore_test_state IN ('untested', 'passed', 'failed')", name="ck_backup_set_restore_test_state"),
    )
    op.create_index("idx_backup_set_snapshot", "backup_set", ["snapshot_at"])

    op.create_table(
        "backup_job",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("trigger", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False, server_default=sa.text("'queued'")),
        # Gleiche Anfrage (Doppelklick, Wiederholung nach Netzwerkfehler) -> derselbe Auftrag.
        sa.Column("idempotency_key", sa.Text(), nullable=True, unique=True),
        sa.Column("requested_by_email", sa.Text(), nullable=True),
        sa.Column("backup_set_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("backup_set.id", ondelete="SET NULL"), nullable=True),
        sa.Column("options", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("warning_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        *_lease_columns(),
        sa.CheckConstraint(f"kind IN ({_in(JOB_KINDS)})", name="ck_backup_job_kind"),
        sa.CheckConstraint(f"trigger IN ({_in(JOB_TRIGGERS)})", name="ck_backup_job_trigger"),
        sa.CheckConstraint(f"state IN ({_in(JOB_STATES)})", name="ck_backup_job_state"),
    )
    # Höchstens ein offener Auftrag je Art - ein zweiter Klick oder der Zeitplan liefert den
    # bestehenden Auftrag zurück statt eines parallelen Laufs.
    op.execute(
        f"CREATE UNIQUE INDEX uq_backup_job_open_kind ON backup_job (kind) WHERE state IN ({_in(OPEN_JOB_STATES)})"
    )
    op.create_index("idx_backup_job_created", "backup_job", ["created_at"])
    op.create_foreign_key("fk_backup_set_job", "backup_set", "backup_job", ["job_id"], ["id"], ondelete="SET NULL")

    op.create_table(
        "backup_pool_archive",
        sa.Column("name", sa.Text(), primary_key=True),
        # Borg-Archiv-ID - ändert sich bei borg recreate; weicht sie vom Repository ab, wird der
        # Inhalt neu abgeglichen.
        sa.Column("archive_id", sa.Text(), nullable=True),
        sa.Column("backup_set_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("state", sa.Text(), nullable=False, server_default=sa.text("'active'")),
        sa.Column("object_count", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("total_bytes", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint("state IN ('active', 'gc_pending', 'deleted')", name="ck_backup_pool_archive_state"),
    )
    op.create_table(
        "backup_content",
        sa.Column("sha256", sa.Text(), primary_key=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("pool_archive", sa.Text(), sa.ForeignKey("backup_pool_archive.name", ondelete="CASCADE"), nullable=False),
        # gc_pending: wird von der Garbage Collection gerade entfernt - nicht mehr für neue
        # Sicherungen verwenden (sonst Verweis auf bald gelöschten Inhalt).
        sa.Column("state", sa.Text(), nullable=False, server_default=sa.text("'active'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_backup_content_sha256"),
        sa.CheckConstraint("state IN ('active', 'gc_pending')", name="ck_backup_content_state"),
    )
    op.create_index("idx_backup_content_pool", "backup_content", ["pool_archive"])

    op.create_table(
        "backup_restore_job",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False, server_default=sa.text("'queued'")),
        sa.Column("idempotency_key", sa.Text(), nullable=True, unique=True),
        sa.Column("backup_set_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("backup_set.id", ondelete="SET NULL"), nullable=True),
        sa.Column("archive_name", sa.Text(), nullable=False),
        sa.Column("options", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("plan", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("requested_by_email", sa.Text(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("mfa_verified_at", sa.DateTime(timezone=True), nullable=True),
        *_lease_columns(),
        sa.CheckConstraint(f"kind IN ({_in(RESTORE_KINDS)})", name="ck_backup_restore_job_kind"),
        sa.CheckConstraint(f"state IN ({_in(RESTORE_STATES)})", name="ck_backup_restore_job_state"),
    )
    # Ein Restore gleichzeitig - zwei parallele Restores derselben Installation sind nie gewollt.
    op.execute(
        f"CREATE UNIQUE INDEX uq_backup_restore_job_open ON backup_restore_job ((true)) WHERE state IN ({_in(OPEN_RESTORE_STATES)})"
    )
    op.create_index("idx_backup_restore_job_created", "backup_restore_job", ["created_at"])

    op.create_table(
        "backup_event",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("backup_job.id", ondelete="CASCADE"), nullable=True),
        sa.Column("restore_job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("backup_restore_job.id", ondelete="CASCADE"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("level", sa.Text(), nullable=False, server_default=sa.text("'info'")),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("actor_email", sa.Text(), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("details", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.CheckConstraint("level IN ('info', 'warning', 'error')", name="ck_backup_event_level"),
    )
    op.create_index("idx_backup_event_job", "backup_event", ["job_id", "id"])
    op.create_index("idx_backup_event_restore_job", "backup_event", ["restore_job_id", "id"])

    op.add_column("storage_state", sa.Column("backup_hold_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("storage_state", sa.Column("backup_hold_generation", sa.BigInteger(), nullable=True))
    op.add_column("storage_state", sa.Column("backup_hold_since", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        "ck_storage_state_backup_hold", "storage_state",
        "(backup_hold_id IS NULL) = (backup_hold_generation IS NULL)",
    )

    # Copy-on-Write-Abfrage für Schreiber: liefert den bisherigen Registerstand eines Objekts,
    # wenn gerade ein Backup-Hold auf der Generation liegt, in die der Aufrufer schreibt. Kein
    # Treffer = nichts zu sichern. Bewusst ohne Lock: der Aufrufer hält über
    # storage_begin_write() bereits FOR SHARE auf storage_state.
    op.execute(r"""
        CREATE FUNCTION public.storage_backup_hold(p_namespace text, p_key text, p_generation bigint)
        RETURNS TABLE (hold_id uuid, sha256 text, size_bytes bigint)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
          SELECT s.backup_hold_id, o.sha256, o.size_bytes
          FROM public.storage_state s
          JOIN public.storage_object o ON o.namespace = p_namespace AND o.key = p_key
          WHERE s.id = 1 AND s.backup_hold_id IS NOT NULL AND s.backup_hold_generation = p_generation
            AND o.status = 'active' AND o.sha256 IS NOT NULL
        $$
    """)
    for signature, roles in _FUNCTIONS.items():
        op.execute(f"REVOKE ALL ON FUNCTION public.{signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION public.{signature} TO {roles}")


def downgrade() -> None:
    for signature in _FUNCTIONS:
        op.execute(f"DROP FUNCTION IF EXISTS public.{signature}")
    op.drop_constraint("ck_storage_state_backup_hold", "storage_state", type_="check")
    op.drop_column("storage_state", "backup_hold_since")
    op.drop_column("storage_state", "backup_hold_generation")
    op.drop_column("storage_state", "backup_hold_id")
    op.drop_table("backup_event")
    op.drop_table("backup_restore_job")
    op.drop_table("backup_content")
    op.drop_table("backup_pool_archive")
    op.drop_constraint("fk_backup_set_job", "backup_set", type_="foreignkey")
    op.drop_table("backup_job")
    op.drop_table("backup_set")
    op.drop_table("backup_settings")
